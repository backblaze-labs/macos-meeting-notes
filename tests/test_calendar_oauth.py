"""Log-safe bounded OAuth and exact token persistence tests."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pytest
from calendar_client_fakes import (
    FakeFlow,
    InMemoryTokenStore,
    authorized_token_json,
    desktop_client_config,
)

from meeting_memory.repo.calendar_client import GoogleCalendarClient
from meeting_memory.repo.calendar_oauth import (
    MAX_OAUTH_TOKEN_BYTES,
    CalendarAuthorizationError,
    CalendarAuthorizationUncertain,
    write_verified_token,
)


def test_auth_flow_is_bounded_and_suppresses_authorization_url(
    monkeypatch,
    capsys,
    caplog,
    tmp_path: Path,
) -> None:
    sentinel = "oauth-state-secret-sentinel"

    class PrintingFlow(FakeFlow):
        def run_local_server(self, **kwargs):
            if kwargs.get("authorization_prompt_message"):
                sys.stdout.write(f"https://accounts.example/auth?state={sentinel}\n")
            return super().run_local_server(**kwargs)

    flow = PrintingFlow()
    monkeypatch.setattr(
        "meeting_memory.repo.calendar_client._load_installed_app_flow",
        lambda: flow,
    )
    caplog.set_level(logging.DEBUG)
    credentials_path = tmp_path / "credentials.json"
    credentials_path.write_text(json.dumps(desktop_client_config()), encoding="utf-8")

    GoogleCalendarClient(
        credentials_file=credentials_path,
        token_store=InMemoryTokenStore(),
    ).authenticate(timeout_seconds=37)

    captured = capsys.readouterr()
    assert captured.out == captured.err == ""
    assert sentinel not in caplog.text
    assert flow.run_kwargs == {
        "timeout_seconds": 37,
        "authorization_prompt_message": "",
        "success_message": "Authorization complete. Return to Meeting Memory.",
        "open_browser": True,
        "prompt": "consent",
    }


def test_store_then_raise_exact_readback_is_treated_as_saved() -> None:
    store = LateRaisingTokenStore()
    token_json = authorized_token_json("token-secret-sentinel")

    write_verified_token(store, token_json)

    assert store.token == token_json


def test_token_readback_uncertainty_is_typed_and_redacted() -> None:
    store = LateRaisingTokenStore(read_fails=True)
    token_json = authorized_token_json("token-secret-sentinel")

    with pytest.raises(CalendarAuthorizationUncertain) as caught:
        write_verified_token(store, token_json)

    assert "token-secret-sentinel" not in repr(caught.value)
    assert "token-secret-sentinel" not in str(caught.value)


def test_definite_token_write_failure_is_typed_and_redacted() -> None:
    store = MissingTokenStore()

    with pytest.raises(CalendarAuthorizationError) as caught:
        write_verified_token(store, authorized_token_json("token-secret-sentinel"))

    assert not isinstance(caught.value, CalendarAuthorizationUncertain)
    assert "token-secret-sentinel" not in str(caught.value)


@pytest.mark.parametrize(
    "token_json",
    [
        "not-json-token-secret-sentinel",
        json.dumps({"refresh_token": "only-token-secret-sentinel"}),
        json.dumps(
            {
                "refresh_token": "refresh",
                "client_id": "client",
                "client_secret": "secret",
                "token_uri": "https://oauth2.googleapis.com/evil",
            }
        ),
        "x" * (MAX_OAUTH_TOKEN_BYTES + 1),
    ],
)
def test_invalid_or_oversize_token_is_rejected_before_store(
    token_json: str,
) -> None:
    store = CountingTokenStore()

    with pytest.raises(CalendarAuthorizationError) as caught:
        write_verified_token(store, token_json)

    assert store.writes == []
    assert "token-secret-sentinel" not in str(caught.value)


class LateRaisingTokenStore:
    def __init__(self, *, read_fails: bool = False) -> None:
        self.token: str | None = None
        self.read_fails = read_fails

    def write_token(self, token_json: str) -> None:
        self.token = token_json
        raise RuntimeError("token-secret-sentinel")

    def read_token(self) -> str | None:
        if self.read_fails:
            raise RuntimeError("token-secret-sentinel")
        return self.token


class MissingTokenStore:
    def write_token(self, _token_json: str) -> None:
        raise RuntimeError("token-secret-sentinel")

    def read_token(self) -> None:
        return None


class CountingTokenStore:
    def __init__(self) -> None:
        self.writes: list[str] = []

    def write_token(self, token_json: str) -> None:
        self.writes.append(token_json)

    def read_token(self) -> None:
        return None

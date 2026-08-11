"""Pinned bounded Desktop OAuth client source validation."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from calendar_client_fakes import FakeFlow, InMemoryTokenStore, desktop_client_config

from meeting_memory.repo import calendar_oauth
from meeting_memory.repo.calendar_oauth import (
    MAX_OAUTH_CONFIG_BYTES,
    CalendarAuthorizationError,
    authorize_calendar,
)


@pytest.mark.parametrize("kind", ["symlink", "fifo", "oversize"])
def test_unsafe_oauth_source_is_rejected_before_flow_or_token_write(
    tmp_path: Path,
    kind: str,
) -> None:
    path = tmp_path / "credentials.json"
    if kind == "symlink":
        target = tmp_path / "target.json"
        target.write_text(json.dumps(desktop_client_config()), encoding="utf-8")
        path.symlink_to(target)
    elif kind == "fifo":
        os.mkfifo(path)
    else:
        path.write_bytes(b"x" * (MAX_OAUTH_CONFIG_BYTES + 1))
    flow = FakeFlow()
    tokens = InMemoryTokenStore()

    with pytest.raises(CalendarAuthorizationError):
        authorize_calendar(flow, path, ("scope",), tokens, timeout_seconds=5)

    assert flow.client_config is None
    assert tokens.token_json is None


@pytest.mark.parametrize(
    "payload",
    [
        {"web": desktop_client_config()["installed"]},
        {
            "installed": {
                **desktop_client_config()["installed"],
                "token_uri": "https://attacker.example/token",
            }
        },
        {
            "installed": {
                **desktop_client_config()["installed"],
                "redirect_uris": ["https://attacker.example/callback"],
            }
        },
        {
            "installed": {
                **desktop_client_config()["installed"],
                "auth_uri": "https://accounts.google.com:444/evil",
            }
        },
        {
            "installed": {
                **desktop_client_config()["installed"],
                "auth_uri": "https://accounts.google.com/arbitrary",
            }
        },
        {
            "installed": {
                **desktop_client_config()["installed"],
                "token_uri": "https://oauth2.googleapis.com:444/token",
            }
        },
    ],
)
def test_non_desktop_or_foreign_oauth_config_is_rejected(
    tmp_path: Path,
    payload: dict[str, object],
) -> None:
    path = tmp_path / "credentials.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    flow = FakeFlow()

    with pytest.raises(CalendarAuthorizationError):
        authorize_calendar(
            flow,
            path,
            ("scope",),
            InMemoryTokenStore(),
            timeout_seconds=5,
        )

    assert flow.client_config is None


def test_oauth_source_mutation_during_read_is_rejected(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "credentials.json"
    path.write_text(json.dumps(desktop_client_config()), encoding="utf-8")
    original_read = calendar_oauth.os.read
    mutated = False

    def mutate_after_read(descriptor: int, size: int) -> bytes:
        nonlocal mutated
        content = original_read(descriptor, size)
        if content and not mutated:
            mutated = True
            path.write_text(json.dumps(desktop_client_config()) + " ", encoding="utf-8")
        return content

    monkeypatch.setattr(calendar_oauth.os, "read", mutate_after_read)
    flow = FakeFlow()

    with pytest.raises(CalendarAuthorizationError):
        authorize_calendar(
            flow,
            path,
            ("scope",),
            InMemoryTokenStore(),
            timeout_seconds=5,
        )

    assert flow.client_config is None


def test_oauth_source_rejects_intermediate_parent_symlink(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    credentials = target / "credentials.json"
    credentials.write_text(json.dumps(desktop_client_config()), encoding="utf-8")
    linked = tmp_path / "linked"
    linked.symlink_to(target, target_is_directory=True)
    flow = FakeFlow()
    tokens = InMemoryTokenStore()

    with pytest.raises(CalendarAuthorizationError):
        authorize_calendar(
            flow,
            linked / "credentials.json",
            ("scope",),
            tokens,
            timeout_seconds=5,
        )

    assert flow.client_config is None
    assert tokens.token_json is None

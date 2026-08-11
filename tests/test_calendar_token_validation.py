"""Strict Calendar token validation before SDK or provider work."""

from __future__ import annotations

import json

import pytest
from calendar_client_fakes import InMemoryTokenStore

from meeting_memory.repo import calendar_client
from meeting_memory.repo.calendar_client import GoogleCalendarClient


def test_runtime_rejects_invalid_keychain_token_before_credentials(
    monkeypatch,
    tmp_path,
) -> None:
    invalid_tokens = (
        '{"refresh_token":"one","refresh_token":"two","client_id":"id","client_secret":"secret"}',
        json.dumps(
            {
                "refresh_token": "refresh",
                "client_id": "id",
                "client_secret": "secret",
                "token_uri": "https://oauth2.googleapis.com/foreign",
            }
        ),
        "x" * 1_048_577,
    )
    credentials_calls = 0

    def credentials_class():
        nonlocal credentials_calls
        credentials_calls += 1
        raise AssertionError("invalid token must not reach Google credentials")

    monkeypatch.setattr(calendar_client, "_load_google_credentials", credentials_class)
    for token in invalid_tokens:
        client = GoogleCalendarClient(
            credentials_file=tmp_path / "credentials.json",
            token_store=InMemoryTokenStore(token),
        )
        with pytest.raises(RuntimeError, match="authorization is invalid"):
            client.credentials()

    assert credentials_calls == 0

"""Tests for the Google Calendar adapter."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from meeting_memory.config.settings import Settings
from meeting_memory.repo import calendar_client
from meeting_memory.repo.calendar_client import (
    GOOGLE_CALENDAR_SCOPE,
    GoogleCalendarClient,
    KeychainTokenStore,
)


def test_calendar_auth_stores_oauth_token(monkeypatch, tmp_path: Path) -> None:
    token_store = InMemoryTokenStore()
    fake_flow = FakeFlow()
    monkeypatch.setattr(calendar_client, "_load_installed_app_flow", lambda: fake_flow)

    credentials = GoogleCalendarClient(
        credentials_file=tmp_path / "credentials.json",
        token_store=token_store,
    ).authenticate()

    assert credentials.token == "fresh-token"
    assert fake_flow.secrets_file == str(tmp_path / "credentials.json")
    assert fake_flow.scopes == [GOOGLE_CALENDAR_SCOPE]
    assert token_store.token_json == '{"token": "fresh-token"}'


def test_calendar_credentials_refresh_expired_token(monkeypatch, tmp_path: Path) -> None:
    token_store = InMemoryTokenStore('{"token":"old"}')
    monkeypatch.setattr(calendar_client, "_load_google_credentials", lambda: FakeCredentials)
    monkeypatch.setattr(calendar_client, "_load_request", lambda: FakeRequest)

    credentials = GoogleCalendarClient(
        credentials_file=tmp_path / "credentials.json",
        token_store=token_store,
    ).credentials()

    assert credentials.refreshed is True
    assert token_store.token_json == '{"token": "refreshed"}'


def test_calendar_lists_only_video_meetings(monkeypatch, tmp_path: Path) -> None:
    token_store = InMemoryTokenStore('{"token":"valid"}')
    fake_service = FakeCalendarService()
    monkeypatch.setattr(calendar_client, "_load_google_credentials", lambda: ValidCredentials)
    monkeypatch.setattr(calendar_client, "_load_google_build", lambda: fake_service.build)

    client = GoogleCalendarClient(
        credentials_file=tmp_path / "credentials.json",
        calendar_id="primary",
        token_store=token_store,
    )
    meetings = client.list_upcoming_meetings(
        now=datetime(2026, 6, 11, 9, 0, tzinfo=UTC),
        lookahead_minutes=7,
    )

    assert len(meetings) == 2
    assert meetings[0].event_id == "meet"
    assert meetings[0].calendar_title == "Daily Standup"
    assert meetings[0].meeting_url == "https://meet.google.com/abc-defg-hij"
    assert meetings[1].meeting_url == "https://acme.zoom.us/j/123456789"
    assert fake_service.list_kwargs["calendarId"] == "primary"
    assert fake_service.list_kwargs["singleEvents"] is True
    assert fake_service.list_kwargs["orderBy"] == "startTime"


def test_keychain_token_store_uses_keyring(monkeypatch) -> None:
    fake_keyring = FakeKeyring()
    monkeypatch.setattr(calendar_client, "_load_keyring", lambda: fake_keyring)

    store = KeychainTokenStore(service="svc", username="user")
    store.write_token("token-json")

    assert store.read_token() == "token-json"
    assert fake_keyring.values == {("svc", "user"): "token-json"}


def test_calendar_client_from_settings(tmp_path: Path) -> None:
    settings = Settings(
        b2_application_key_id="key-id",
        b2_application_key="secret",
        b2_endpoint="https://s3.example.com",
        b2_region="us-west-004",
        b2_bucket_name="bucket",
        assemblyai_api_key="assembly-key",
        google_calendar_credentials_file=tmp_path / "credentials.json",
        google_calendar_id="primary",
    )

    client = GoogleCalendarClient.from_settings(settings)

    assert client.credentials_file == tmp_path / "credentials.json"
    assert client.calendar_id == "primary"


class InMemoryTokenStore:
    def __init__(self, token_json: str | None = None):
        self.token_json = token_json

    def read_token(self) -> str | None:
        return self.token_json

    def write_token(self, token_json: str) -> None:
        self.token_json = token_json


class FakeOAuthCredentials:
    token = "fresh-token"

    def to_json(self) -> str:
        return json.dumps({"token": self.token})


class FakeFlow:
    secrets_file: str | None = None
    scopes: list[str] | None = None

    def from_client_secrets_file(self, secrets_file: str, scopes: list[str]):
        self.secrets_file = secrets_file
        self.scopes = scopes
        return self

    def run_local_server(self, *, port: int) -> FakeOAuthCredentials:
        assert port == 0
        return FakeOAuthCredentials()


class FakeCredentials:
    valid = False
    expired = True
    refresh_token = "refresh-token"

    def __init__(self):
        self.refreshed = False

    @classmethod
    def from_authorized_user_info(cls, info: dict[str, str], scopes: list[str]):
        assert info == {"token": "old"}
        assert scopes == [GOOGLE_CALENDAR_SCOPE]
        return cls()

    def refresh(self, request) -> None:
        assert isinstance(request, FakeRequest)
        self.refreshed = True

    def to_json(self) -> str:
        return json.dumps({"token": "refreshed"})


class ValidCredentials:
    valid = True

    @classmethod
    def from_authorized_user_info(cls, info: dict[str, str], scopes: list[str]):
        assert info == {"token": "valid"}
        assert scopes == [GOOGLE_CALENDAR_SCOPE]
        return cls()


class FakeRequest:
    pass


class FakeCalendarService:
    def __init__(self):
        self.list_kwargs = {}

    def build(self, service_name: str, version: str, *, credentials):
        assert service_name == "calendar"
        assert version == "v3"
        assert isinstance(credentials, ValidCredentials)
        return self

    def events(self):
        return self

    def list(self, **kwargs):
        self.list_kwargs = kwargs
        return self

    def execute(self):
        return {
            "items": [
                {
                    "id": "meet",
                    "summary": "Daily Standup",
                    "description": "Join https://meet.google.com/abc-defg-hij",
                    "start": {"dateTime": "2026-06-11T09:05:00+00:00"},
                },
                {
                    "id": "zoom",
                    "summary": "Customer Call",
                    "location": "https://acme.zoom.us/j/123456789",
                    "start": {"dateTime": "2026-06-11T09:06:00Z"},
                },
                {
                    "id": "focus",
                    "summary": "Focus Time",
                    "description": "No meeting link",
                    "start": {"dateTime": "2026-06-11T09:07:00+00:00"},
                },
            ]
        }


class FakeKeyring:
    def __init__(self):
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.values.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.values[(service, username)] = password

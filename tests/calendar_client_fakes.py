"""Fakes used by Google Calendar adapter tests."""

from __future__ import annotations

import json

from meeting_memory.repo.calendar_client import GOOGLE_CALENDAR_SCOPE


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
        return authorized_token_json(self.token)


class FakeFlow:
    client_config: dict[str, object] | None = None
    scopes: list[str] | None = None

    def from_client_config(self, client_config: dict[str, object], scopes: list[str]):
        self.client_config = client_config
        self.scopes = scopes
        return self

    run_kwargs: dict[str, object] | None = None

    def run_local_server(self, *, port: int, **kwargs) -> FakeOAuthCredentials:
        assert port == 0
        self.run_kwargs = kwargs
        return FakeOAuthCredentials()


def desktop_client_config() -> dict[str, object]:
    return {
        "installed": {
            "client_id": "desktop-client-id",
            "client_secret": "desktop-client-secret",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }


class FakeCredentials:
    valid = False
    expired = True
    refresh_token = "refresh-token"

    def __init__(self):
        self.refreshed = False

    @classmethod
    def from_authorized_user_info(cls, info: dict[str, str], scopes: list[str]):
        assert info == json.loads(authorized_token_json("old"))
        assert scopes == [GOOGLE_CALENDAR_SCOPE]
        return cls()

    def refresh(self, request) -> None:
        assert isinstance(request, FakeRequest)
        self.refreshed = True

    def to_json(self) -> str:
        return authorized_token_json("refreshed")


class ValidCredentials:
    valid = True

    @classmethod
    def from_authorized_user_info(cls, info: dict[str, str], scopes: list[str]):
        assert info == json.loads(authorized_token_json("valid"))
        assert scopes == [GOOGLE_CALENDAR_SCOPE]
        return cls()


class FakeRequest:
    pass


def authorized_token_json(token: str = "fresh-token") -> str:
    return json.dumps(
        {
            "token": token,
            "refresh_token": "refresh-token",
            "client_id": "desktop-client-id",
            "client_secret": "desktop-client-secret",
            "token_uri": "https://oauth2.googleapis.com/token",
            "scopes": [GOOGLE_CALENDAR_SCOPE],
        }
    )


class FakeCalendarService:
    def __init__(self):
        self.list_kwargs = {}
        self.list_calls = []

    def build(self, service_name: str, version: str, *, http, cache_discovery: bool):
        assert service_name == "calendar"
        assert version == "v3"
        assert isinstance(http.credentials, ValidCredentials)
        assert cache_discovery is False
        return self

    def events(self):
        return self

    def list(self, **kwargs):
        self.list_kwargs = kwargs
        self.list_calls.append(kwargs)
        return self

    def calendarList(self):
        return FakeCalendarList()

    def execute(self):
        return {
            "items": [
                {
                    "id": "meet",
                    "summary": "Daily Standup",
                    "description": "Join https://meet.google.com/abc-defg-hij",
                    "start": {"dateTime": "2026-06-11T09:05:00+00:00"},
                    "end": {"dateTime": "2026-06-11T09:30:00+00:00"},
                },
                {
                    "id": "zoom",
                    "summary": "Customer Call",
                    "location": "https://acme.zoom.us/j/123456789",
                    "start": {"dateTime": "2026-06-11T09:06:00Z"},
                    "end": {"dateTime": "2026-06-11T09:45:00Z"},
                },
                {
                    "id": "focus",
                    "summary": "Focus Time",
                    "description": "No meeting link",
                    "start": {"dateTime": "2026-06-11T09:07:00+00:00"},
                },
            ]
        }


class FakeCalendarList:
    def list(self):
        return self

    def execute(self):
        return {"items": [{"id": "primary"}, {"id": "team"}, {"id": "deleted", "deleted": True}]}

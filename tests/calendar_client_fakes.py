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
        self.list_calls = []

    def build(self, service_name: str, version: str, *, credentials):
        assert service_name == "calendar"
        assert version == "v3"
        assert isinstance(credentials, ValidCredentials)
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

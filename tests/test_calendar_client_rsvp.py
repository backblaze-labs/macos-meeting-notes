"""RSVP filtering tests for the Google Calendar adapter."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from meeting_memory.repo import calendar_client
from meeting_memory.repo.calendar_client import GOOGLE_CALENDAR_SCOPE, GoogleCalendarClient


def test_calendar_lists_skip_self_declined_video_meetings(monkeypatch, tmp_path: Path) -> None:
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

    assert [meeting.event_id for meeting in meetings] == ["accepted"]
    assert meetings[0].calendar_title == "Accepted Sync"


class InMemoryTokenStore:
    def __init__(self, token_json: str | None = None):
        self.token_json = token_json

    def read_token(self) -> str | None:
        return self.token_json

    def write_token(self, token_json: str) -> None:
        self.token_json = token_json


class ValidCredentials:
    valid = True

    @classmethod
    def from_authorized_user_info(cls, info: dict[str, str], scopes: list[str]):
        assert info == {"token": "valid"}
        assert scopes == [GOOGLE_CALENDAR_SCOPE]
        return cls()


class FakeCalendarService:
    def build(self, service_name: str, version: str, *, credentials):
        assert service_name == "calendar"
        assert version == "v3"
        assert isinstance(credentials, ValidCredentials)
        return self

    def events(self):
        return self

    def list(self, **kwargs):
        return self

    def execute(self):
        return {
            "items": [
                _event(
                    "declined",
                    "Declined Sync",
                    [{"email": "me@example.com", "self": True, "responseStatus": "declined"}],
                ),
                _event(
                    "accepted",
                    "Accepted Sync",
                    [
                        {"email": "teammate@example.com", "responseStatus": "declined"},
                        {"email": "me@example.com", "self": True, "responseStatus": "accepted"},
                    ],
                ),
            ]
        }


def _event(event_id: str, title: str, attendees: list[dict[str, object]]) -> dict[str, object]:
    return {
        "id": event_id,
        "summary": title,
        "description": f"Join https://meet.google.com/{event_id}-sync",
        "start": {"dateTime": "2026-06-11T09:05:00+00:00"},
        "end": {"dateTime": "2026-06-11T09:30:00+00:00"},
        "attendees": attendees,
    }

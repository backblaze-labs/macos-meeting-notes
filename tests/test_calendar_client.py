"""Tests for the Google Calendar adapter."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from calendar_client_fakes import (
    FakeCalendarService,
    FakeCredentials,
    FakeFlow,
    FakeRequest,
    InMemoryTokenStore,
    ValidCredentials,
)

from meeting_memory.config.settings import Settings
from meeting_memory.repo import calendar_client
from meeting_memory.repo.calendar_client import (
    GOOGLE_CALENDAR_SCOPE,
    GoogleCalendarClient,
    KeychainTokenStore,
)
from meeting_memory.types.speakers import KnownSpeaker


def test_calendar_auth_stores_oauth_token(monkeypatch, tmp_path: Path):
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


def test_calendar_credentials_refresh_expired_token(monkeypatch, tmp_path: Path):
    token_store = InMemoryTokenStore('{"token":"old"}')
    monkeypatch.setattr(calendar_client, "_load_google_credentials", lambda: FakeCredentials)
    monkeypatch.setattr(calendar_client, "_load_request", lambda: FakeRequest)

    credentials = GoogleCalendarClient(
        credentials_file=tmp_path / "credentials.json",
        token_store=token_store,
    ).credentials()

    assert credentials.refreshed is True
    assert token_store.token_json == '{"token": "refreshed"}'


def test_calendar_lists_only_video_meetings(monkeypatch, tmp_path: Path):
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
    assert meetings[0].ends_at == datetime(2026, 6, 11, 9, 30, tzinfo=UTC)
    assert meetings[0].speaker_candidates == ()
    assert meetings[1].meeting_url == "https://acme.zoom.us/j/123456789"
    assert fake_service.list_kwargs["calendarId"] == "primary"
    assert fake_service.list_kwargs["singleEvents"] is True
    assert fake_service.list_kwargs["orderBy"] == "startTime"


def test_calendar_extracts_conference_data_meeting_urls():
    zoom_url = "https://acme.zoom.us/j/123456789?pwd=example&jst=2"
    cases = [
        {
            "conferenceData": {
                "entryPoints": [
                    {"entryPointType": "phone", "uri": "tel:+15550101010,,123456789#"},
                    {"entryPointType": "video", "uri": zoom_url},
                ],
            }
        },
        {
            "conferenceData": {
                "notes": (
                    'Join Zoom Meeting: <a href="https://www.google.com/url?'
                    "q=https%3A%2F%2Facme.zoom.us%2Fj%2F123456789%3F"
                    f'pwd%3Dexample%26jst%3D2&amp;sa=D">{zoom_url}</a>'
                )
            }
        },
    ]

    for event_data in cases:
        meeting = calendar_client._meeting_from_event(
            {
                "id": "zoom-addon",
                "summary": "Claude Code 202",
                "description": "The event description has no meeting URL.",
                "start": {"dateTime": "2026-06-11T09:05:00+00:00"},
                "end": {"dateTime": "2026-06-11T09:30:00+00:00"},
                **event_data,
            }
        )
        assert meeting is not None
        assert meeting.meeting_url == zoom_url


def test_calendar_speaker_candidates_include_attendees_with_team_aliases():
    candidates = calendar_client._speaker_candidates(
        {
            "attendees": [
                {"displayName": "Casey Garcia", "email": "someone@example.com"},
                {"displayName": "Ada Lovelace", "email": "ada.lovelace@example.com"},
                {"name": "Unrelated Person", "email": "drew@example.com"},
                {"displayName": "Not Known", "email": "alex.rivera@example.com"},
                {"email": "blair+calendar@example.com"},
                {"displayName": "Jody Example", "email": "jody@example.com"},
                {"displayName": "Conference Room", "resource": True},
                {"displayName": "Declined Person", "responseStatus": "declined"},
            ],
        },
        ("Alex", "Casey", "Drew", "Blair"),
    )

    assert candidates == (
        "Casey",
        "Ada Lovelace",
        "Drew",
        "Alex",
        "Blair",
        "Jody Example",
    )


def test_calendar_suggests_candidates_from_email_names_when_names_are_missing():
    candidates = calendar_client._speaker_candidates(
        {
            "attendees": [
                {"email": "blair.chen@example.com"},
                {"email": "casey.jones@example.com"},
                {"email": "alex.rivera@example.com"},
            ],
        },
        ("Alex", "Casey", "Drew", "Blair"),
    )

    assert candidates == ("Blair", "Casey", "Alex")


def test_calendar_does_not_add_unmatched_known_speakers_to_candidates():
    candidates = calendar_client._speaker_candidates(
        {
            "attendees": [
                {"displayName": "Ada Lovelace", "email": "ada.lovelace@example.com"},
            ],
        },
        ("Alex", "Blair"),
    )

    assert candidates == ("Ada Lovelace",)


def test_calendar_known_speakers_can_match_configured_email_aliases():
    candidates = calendar_client._speaker_candidates(
        {
            "attendees": [
                {"email": "alex@example.com"},
                {"email": "blair@example.com"},
            ],
        },
        (
            KnownSpeaker("Alex", ("alex",)),
            KnownSpeaker("Blair", ("blair@example.com",)),
        ),
    )

    assert candidates == ("Alex", "Blair")


def test_calendar_email_matching_does_not_use_first_initial_only():
    candidates = calendar_client._speaker_candidates(
        {
            "attendees": [
                {"email": "sales@example.com"},
            ],
        },
        ("Casey",),
    )

    assert candidates == ("sales@example.com",)


def test_calendar_lists_all_accessible_calendars(monkeypatch, tmp_path: Path):
    token_store = InMemoryTokenStore('{"token":"valid"}')
    fake_service = FakeCalendarService()
    monkeypatch.setattr(calendar_client, "_load_google_credentials", lambda: ValidCredentials)
    monkeypatch.setattr(calendar_client, "_load_google_build", lambda: fake_service.build)

    client = GoogleCalendarClient(
        credentials_file=tmp_path / "credentials.json",
        calendar_id="all",
        token_store=token_store,
    )
    meetings = client.list_upcoming_meetings(
        now=datetime(2026, 6, 11, 9, 0, tzinfo=UTC),
        lookahead_minutes=7,
        lookbehind_minutes=5,
    )

    assert [call["calendarId"] for call in fake_service.list_calls] == ["primary", "team"]
    assert [meeting.calendar_title for meeting in meetings] == [
        "Daily Standup",
        "Daily Standup",
        "Customer Call",
        "Customer Call",
    ]


def test_keychain_token_store_uses_keyring(monkeypatch):
    fake_keyring = FakeKeyring()
    monkeypatch.setattr(calendar_client, "_load_keyring", lambda: fake_keyring)

    store = KeychainTokenStore(service="svc", username="user")
    store.write_token("token-json")

    assert store.read_token() == "token-json"
    assert fake_keyring.values == {("svc", "user"): "token-json"}


def test_calendar_client_from_settings(tmp_path: Path):
    settings = Settings(
        _env_file=None,
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
    assert client.known_speakers == ()


class FakeKeyring:
    def __init__(self):
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.values.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.values[(service, username)] = password

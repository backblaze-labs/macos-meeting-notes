"""Google Calendar OAuth and event polling adapter."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

from meeting_memory.config.settings import Settings
from meeting_memory.types.meeting import CalendarMeeting

GOOGLE_CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
KEYCHAIN_SERVICE = "meeting-memory.google-calendar"
KEYCHAIN_USERNAME = "oauth-token"
MEETING_URL_RE = re.compile(r"(https?://)?(meet\.google\.com/\S+|[\w.-]*zoom\.us/[js]/\S+)")
ALL_CALENDARS = "all"


class TokenStore(Protocol):
    def read_token(self) -> str | None:
        """Read serialized OAuth credentials."""

    def write_token(self, token_json: str) -> None:
        """Persist serialized OAuth credentials."""


@dataclass(frozen=True)
class KeychainTokenStore:
    service: str = KEYCHAIN_SERVICE
    username: str = KEYCHAIN_USERNAME

    def read_token(self) -> str | None:
        return _load_keyring().get_password(self.service, self.username)

    def write_token(self, token_json: str) -> None:
        _load_keyring().set_password(self.service, self.username, token_json)


@dataclass(frozen=True)
class GoogleCalendarClient:
    credentials_file: Path
    calendar_id: str = "primary"
    token_store: TokenStore = field(default_factory=KeychainTokenStore)
    scopes: tuple[str, ...] = (GOOGLE_CALENDAR_SCOPE,)

    @classmethod
    def from_settings(cls, settings: Settings) -> GoogleCalendarClient:
        return cls(
            credentials_file=settings.google_credentials_path,
            calendar_id=settings.google_calendar_id,
        )

    def authenticate(self):
        flow_cls = _load_installed_app_flow()
        flow = flow_cls.from_client_secrets_file(str(self.credentials_file), list(self.scopes))
        credentials = flow.run_local_server(port=0)
        self.token_store.write_token(credentials.to_json())
        return credentials

    def credentials(self, *, interactive: bool = False):
        token_json = self.token_store.read_token()
        if token_json:
            credentials = self._credentials_from_token(token_json)
            if getattr(credentials, "valid", False):
                return credentials
            can_refresh = getattr(credentials, "expired", False) and getattr(
                credentials,
                "refresh_token",
                None,
            )
            if can_refresh:
                credentials.refresh(_load_request()())
                self.token_store.write_token(credentials.to_json())
                return credentials

        if interactive:
            return self.authenticate()
        raise RuntimeError("Google Calendar is not authenticated. Run `meeting-memory auth`.")

    def list_upcoming_meetings(
        self,
        *,
        now: datetime,
        lookahead_minutes: int,
        lookbehind_minutes: int = 0,
    ) -> list[CalendarMeeting]:
        service = _load_google_build()("calendar", "v3", credentials=self.credentials())
        meetings: list[CalendarMeeting] = []
        for calendar_id in self._calendar_ids(service):
            response = (
                service.events()
                .list(
                    calendarId=calendar_id,
                    timeMin=(now - timedelta(minutes=lookbehind_minutes)).isoformat(),
                    timeMax=(now + timedelta(minutes=lookahead_minutes)).isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
            meetings.extend(
                meeting
                for item in response.get("items", ())
                if (meeting := _meeting_from_event(item))
            )
        return sorted(meetings, key=lambda meeting: meeting.starts_at)

    def _credentials_from_token(self, token_json: str):
        credentials_cls = _load_google_credentials()
        return credentials_cls.from_authorized_user_info(json.loads(token_json), list(self.scopes))

    def _calendar_ids(self, service) -> list[str]:
        if self.calendar_id.strip().lower() != ALL_CALENDARS:
            return [self.calendar_id]

        response = service.calendarList().list().execute()
        return [
            str(item["id"])
            for item in response.get("items", ())
            if item.get("id") and not item.get("deleted")
        ]


def _meeting_from_event(item: dict[str, object]) -> CalendarMeeting | None:
    meeting_url = _extract_meeting_url(item)
    if meeting_url is None:
        return None
    return CalendarMeeting(
        event_id=str(item.get("id") or ""),
        calendar_title=str(item.get("summary") or "Untitled"),
        starts_at=_parse_start(item),
        meeting_url=meeting_url,
        ends_at=_parse_end(item),
    )


def _extract_meeting_url(item: dict[str, object]) -> str | None:
    candidates = (
        str(item.get("description") or ""),
        str(item.get("location") or ""),
        str(item.get("hangoutLink") or ""),
    )
    for candidate in candidates:
        match = MEETING_URL_RE.search(candidate)
        if match:
            return match.group(0)
    return None


def _parse_start(item: dict[str, object]) -> datetime:
    return _parse_time(item, "start")


def _parse_end(item: dict[str, object]) -> datetime | None:
    try:
        return _parse_time(item, "end")
    except ValueError:
        return None


def _parse_time(item: dict[str, object], field_name: str) -> datetime:
    value = item.get(field_name)
    if not isinstance(value, dict):
        raise ValueError(f"calendar event is missing {field_name} time")
    raw_value = str(value.get("dateTime") or value.get("date"))
    return datetime.fromisoformat(raw_value.replace("Z", "+00:00"))


def _load_keyring():
    import keyring

    return keyring


def _load_installed_app_flow():
    from google_auth_oauthlib.flow import InstalledAppFlow

    return InstalledAppFlow


def _load_google_credentials():
    from google.oauth2.credentials import Credentials

    return Credentials


def _load_request():
    from google.auth.transport.requests import Request

    return Request


def _load_google_build():
    from googleapiclient.discovery import build

    return build

"""Google Calendar OAuth and event polling adapter."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from html import unescape
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from meeting_memory.config.settings import Settings
from meeting_memory.repo.calendar_oauth import (
    TokenStore,
    authorize_calendar,
    is_valid_calendar_token_json,
    write_verified_token,
)
from meeting_memory.repo.google_http import authorized_google_http
from meeting_memory.repo.speaker_candidates import (
    speaker_candidates_from_event as _speaker_candidates,
)
from meeting_memory.types.egress import EgressPaused
from meeting_memory.types.meeting import CalendarMeeting
from meeting_memory.types.speakers import KnownSpeaker

GOOGLE_CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
KEYCHAIN_SERVICE = "meeting-memory.google-calendar"
KEYCHAIN_USERNAME = "oauth-token"
MEETING_URL_RE = re.compile(
    r"(https?://)?(meet\.google\.com/[^\s<>'\"]+|[\w.-]*zoom\.us/[js]/[^\s<>'\"]+)"
)
GOOGLE_REDIRECT_RE = re.compile(r"https://www\.google\.com/url\?[^\s<>'\"]+")
ALL_CALENDARS = "all"


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
    known_speakers: tuple[KnownSpeaker, ...] = ()
    token_store: TokenStore = field(default_factory=KeychainTokenStore)
    scopes: tuple[str, ...] = (GOOGLE_CALENDAR_SCOPE,)
    admit_request: Callable[[], bool] = field(default=lambda: True, repr=False, compare=False)

    @classmethod
    def from_settings(cls, settings: Settings) -> GoogleCalendarClient:
        return cls(
            credentials_file=settings.google_credentials_path,
            calendar_id=settings.google_calendar_id,
            known_speakers=settings.known_speakers,
        )

    def authenticate(self, *, timeout_seconds: int = 180):
        return authorize_calendar(
            _load_installed_app_flow(),
            self.credentials_file,
            self.scopes,
            self.token_store,
            timeout_seconds=timeout_seconds,
        )

    def credentials(self, *, interactive: bool = False):
        self._require_enabled()
        token_json = self.token_store.read_token()
        if token_json:
            credentials = self._credentials_from_token(token_json)
            if getattr(credentials, "valid", False):
                return credentials
            can_refresh = getattr(credentials, "expired", False) and getattr(
                credentials, "refresh_token", None
            )
            if can_refresh:
                self._require_enabled()
                credentials.refresh(_load_request()())
                write_verified_token(self.token_store, credentials.to_json())
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
        self._require_enabled()
        credentials = self.credentials()
        builder = _load_google_build()
        self._require_enabled()
        service = builder(
            "calendar",
            "v3",
            http=authorized_google_http(credentials),
            cache_discovery=False,
        )
        meetings: list[CalendarMeeting] = []
        for calendar_id in self._calendar_ids(service):
            self._require_enabled()
            request = service.events().list(
                calendarId=calendar_id,
                timeMin=(now - timedelta(minutes=lookbehind_minutes)).isoformat(),
                timeMax=(now + timedelta(minutes=lookahead_minutes)).isoformat(),
                singleEvents=True,
                orderBy="startTime",
            )
            self._require_enabled()
            response = request.execute()
            meetings.extend(
                meeting
                for item in response.get("items", ())
                if (meeting := _meeting_from_event(item, self.known_speakers))
            )
        return sorted(meetings, key=lambda meeting: meeting.starts_at)

    def _credentials_from_token(self, token_json: str):
        if not is_valid_calendar_token_json(token_json):
            raise RuntimeError("Google Calendar authorization is invalid.")
        credentials_cls = _load_google_credentials()
        return credentials_cls.from_authorized_user_info(json.loads(token_json), list(self.scopes))

    def _calendar_ids(self, service) -> list[str]:
        if self.calendar_id.strip().lower() != ALL_CALENDARS:
            return [self.calendar_id]

        self._require_enabled()
        request = service.calendarList().list()
        self._require_enabled()
        response = request.execute()
        return [
            str(item["id"])
            for item in response.get("items", ())
            if item.get("id") and not item.get("deleted")
        ]

    def _require_enabled(self) -> None:
        if not self.admit_request():
            raise EgressPaused("Calendar provider operation is disabled")


def _meeting_from_event(
    item: dict[str, object],
    known_speakers: tuple[KnownSpeaker, ...] = (),
) -> CalendarMeeting | None:
    if _self_declined_event(item):
        return None

    meeting_url = _extract_meeting_url(item)
    if meeting_url is None:
        return None
    return CalendarMeeting(
        event_id=str(item.get("id") or ""),
        calendar_title=str(item.get("summary") or "Untitled"),
        starts_at=_parse_time(item, "start"),
        meeting_url=meeting_url,
        ends_at=_parse_end(item),
        speaker_candidates=_speaker_candidates(item, known_speakers),
    )


def _self_declined_event(item: dict[str, object]) -> bool:
    attendees = item.get("attendees")
    if not isinstance(attendees, list):
        return False

    return any(
        isinstance(attendee, dict)
        and attendee.get("self") is True
        and str(attendee.get("responseStatus") or "").casefold() == "declined"
        for attendee in attendees
    )


def _extract_meeting_url(item: dict[str, object]) -> str | None:
    for candidate in _meeting_url_candidates(item):
        for variant in _candidate_variants(candidate):
            match = MEETING_URL_RE.search(variant)
            if match:
                return _clean_meeting_url(match.group(0))
    return None


def _meeting_url_candidates(item: dict[str, object]) -> Iterator[str]:
    yield from _conference_video_entry_point_values(item)
    yield str(item.get("description") or "")
    yield str(item.get("location") or "")
    yield str(item.get("hangoutLink") or "")

    conference_data = item.get("conferenceData")
    if isinstance(conference_data, dict):
        yield str(conference_data.get("notes") or "")


def _conference_video_entry_point_values(item: dict[str, object]) -> Iterator[str]:
    conference_data = item.get("conferenceData")
    if not isinstance(conference_data, dict):
        return

    entry_points = conference_data.get("entryPoints")
    if not isinstance(entry_points, list):
        return

    for entry_point in entry_points:
        if not isinstance(entry_point, dict):
            continue
        if entry_point.get("entryPointType") != "video":
            continue
        yield str(entry_point.get("uri") or "")
        yield str(entry_point.get("label") or "")


def _candidate_variants(candidate: str) -> list[str]:
    text = unescape(candidate)
    redirect_targets = []
    for match in GOOGLE_REDIRECT_RE.finditer(text):
        query = parse_qs(urlsplit(match.group(0)).query)
        redirect_targets.extend(query.get("q", []))
    return [*redirect_targets, text]


def _clean_meeting_url(raw_url: str) -> str:
    url = unescape(raw_url).strip().rstrip(".,);]")
    if url.startswith(("http://", "https://")):
        return url
    return f"https://{url}"


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

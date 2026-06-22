"""Meeting metadata and slug helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

TITLE_SLUG_MAX_LENGTH = 40
DEFAULT_MEETING_TITLE = "Untitled"


@dataclass(frozen=True)
class MeetingMeta:
    slug: str
    started_at: datetime
    calendar_title: str = DEFAULT_MEETING_TITLE
    duration_minutes: int = 0
    speaker_candidates: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.slug:
            raise ValueError("meeting slug must not be blank")
        if self.duration_minutes < 0:
            raise ValueError("duration_minutes must be >= 0")

    def with_slug(self, slug: str) -> MeetingMeta:
        return replace(self, slug=slug)

    def with_title(self, title: str | None) -> MeetingMeta:
        clean_title = normalized_title(title)
        return replace(
            self,
            slug=build_meeting_slug(self.started_at, clean_title),
            calendar_title=clean_title,
        )

    def with_speaker_candidates(self, speaker_candidates: tuple[str, ...]) -> MeetingMeta:
        return replace(self, speaker_candidates=speaker_candidates)

    @property
    def needs_title_prompt(self) -> bool:
        return normalized_title(self.calendar_title).casefold() == DEFAULT_MEETING_TITLE.casefold()


@dataclass(frozen=True)
class MeetingFiles:
    meta: MeetingMeta
    directory: Path
    audio_path: Path
    markdown_path: Path
    notes_path: Path | None = None

    @property
    def transcript_path(self) -> Path:
        return self.markdown_path


@dataclass(frozen=True)
class B2UploadResult:
    audio_key: str
    transcript_key: str


@dataclass(frozen=True)
class CalendarMeeting:
    event_id: str
    calendar_title: str
    starts_at: datetime
    meeting_url: str
    ends_at: datetime | None = None
    speaker_candidates: tuple[str, ...] = ()


@dataclass(frozen=True)
class RecordingContext:
    calendar_title: str
    ends_at: datetime | None = None
    event_id: str | None = None
    speaker_candidates: tuple[str, ...] = ()


@dataclass(frozen=True)
class RecentMeeting:
    slug: str
    calendar_title: str
    started_at: datetime
    directory: Path
    markdown_path: Path


def slugify_title(title: str, max_length: int = TITLE_SLUG_MAX_LENGTH) -> str:
    normalized = re.sub(r"\s+", "-", title.strip().lower())
    normalized = re.sub(r"[^a-z0-9-]", "", normalized)
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    return normalized[:max_length].strip("-") or "untitled"


def build_meeting_slug(started_at: datetime, title: str) -> str:
    return f"{started_at:%Y-%m-%d_%H-%M}_{slugify_title(title)}"


def normalized_title(title: str | None) -> str:
    if title is None:
        return DEFAULT_MEETING_TITLE
    return title.strip() or DEFAULT_MEETING_TITLE

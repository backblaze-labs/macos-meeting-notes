"""Meeting metadata and slug helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from meeting_memory.types.audio import CaptureDiagnostics

TITLE_SLUG_MAX_LENGTH = 40
DEFAULT_MEETING_TITLE = "Untitled"
CANONICAL_MEETING_SLUG = re.compile(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", flags=re.ASCII)


@dataclass(frozen=True)
class MeetingMeta:
    slug: str
    started_at: datetime
    calendar_title: str = DEFAULT_MEETING_TITLE
    duration_minutes: int = 0
    speaker_candidates: tuple[str, ...] = ()
    capture_diagnostics: CaptureDiagnostics | None = None

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
    extra_audio_paths: tuple[Path, ...] = ()
    directory_identity: MeetingDirectoryIdentity | None = None

    @property
    def transcript_path(self) -> Path:
        return self.markdown_path


@dataclass(frozen=True)
class MeetingDirectoryIdentity:
    """Pinned filesystem identity for one runtime-owned meeting directory."""

    device: int
    inode: int


@dataclass(frozen=True)
class MeetingRef:
    """Stable reference carried by local-first boundary events."""

    slug: str
    calendar_title: str
    directory: Path

    @property
    def audio_path(self) -> Path:
        return self.directory / "recording.m4a"

    @property
    def transcript_path(self) -> Path:
        return self.directory / "transcript.md"


@dataclass(frozen=True)
class PostCommitPolicy:
    """Optional work requested for recordings committed after opt-in."""

    transcription: bool = False
    backup: bool = False


@dataclass(frozen=True)
class B2UploadResult:
    audio_key: str
    transcript_key: str
    audio_keys: tuple[str, ...] = ()


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


def validate_meeting_slug(slug: str) -> str:
    """Require one canonical ASCII path component for a meeting directory."""

    if not isinstance(slug, str) or CANONICAL_MEETING_SLUG.fullmatch(slug) is None:
        raise ValueError("meeting slug must be one canonical ASCII path component")
    return slug


def build_meeting_slug(started_at: datetime, title: str) -> str:
    return f"{started_at:%Y-%m-%d_%H-%M}_{slugify_title(title)}"


def normalized_title(title: str | None) -> str:
    if title is None:
        return DEFAULT_MEETING_TITLE
    return title.strip() or DEFAULT_MEETING_TITLE

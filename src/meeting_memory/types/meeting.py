"""Meeting metadata and slug helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

TITLE_SLUG_MAX_LENGTH = 40


@dataclass(frozen=True)
class MeetingMeta:
    slug: str
    started_at: datetime
    calendar_title: str = "Untitled"
    duration_minutes: int = 0

    def __post_init__(self) -> None:
        if not self.slug:
            raise ValueError("meeting slug must not be blank")
        if self.duration_minutes < 0:
            raise ValueError("duration_minutes must be >= 0")

    def with_slug(self, slug: str) -> MeetingMeta:
        return replace(self, slug=slug)


@dataclass(frozen=True)
class MeetingFiles:
    meta: MeetingMeta
    directory: Path
    audio_path: Path
    markdown_path: Path


@dataclass(frozen=True)
class B2UploadResult:
    audio_key: str
    transcript_key: str


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

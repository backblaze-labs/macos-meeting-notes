"""UI event boundary models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class MeetingDetected:
    event_id: str
    calendar_title: str
    starts_at: datetime
    meeting_url: str
    ends_at: datetime | None = None


@dataclass(frozen=True)
class NotifyEvent:
    title: str
    body: str
    action_label: str | None = None
    action: str | None = None
    meeting_directory: Path | None = None


@dataclass(frozen=True)
class RecordingStateChanged:
    is_recording: bool
    duration_seconds: int = 0
    meeting_slug: str | None = None

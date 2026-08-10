"""UI event boundary models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from meeting_memory.types.meeting import MeetingMeta, MeetingRef
from meeting_memory.types.recovery import RecoveryIndexEntry


@dataclass(frozen=True)
class MeetingDetected:
    event_id: str
    calendar_title: str
    starts_at: datetime
    meeting_url: str
    ends_at: datetime | None = None
    speaker_candidates: tuple[str, ...] = ()


@dataclass(frozen=True)
class NotifyEvent:
    title: str
    body: str
    action_label: str | None = None
    action: str | None = None
    meeting_directory: Path | None = None
    show_notification: bool = True
    rebuild_menu: bool = False


@dataclass(frozen=True)
class RecordingTitleNeeded:
    audio_path: Path
    meta: MeetingMeta
    recovery: RecoveryIndexEntry | None = None


@dataclass(frozen=True)
class RecordingStateChanged:
    is_recording: bool
    duration_seconds: int = 0
    meeting_slug: str | None = None


@dataclass(frozen=True)
class RecordingCommitted:
    """A complete local meeting directory was atomically published."""

    meeting: MeetingRef


@dataclass(frozen=True)
class RecordingPublicationUncertain:
    """A meeting is visible, but parent-directory durability is not confirmed."""

    meeting: MeetingRef


@dataclass(frozen=True)
class RecordingCleanupPending:
    """A durable meeting is visible, but its recovery source still needs cleanup."""

    meeting: MeetingRef


@dataclass(frozen=True)
class TranscriptReady:
    """A committed meeting now has a successful transcript."""

    meeting: MeetingRef


@dataclass(frozen=True)
class TranscriptionFailed:
    """Transcription failed while the committed local audio remains safe."""

    meeting: MeetingRef

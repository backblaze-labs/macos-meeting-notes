"""Pure local-artifact ownership and state boundary data."""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import BinaryIO

from meeting_memory.types.capabilities import MeetingJobState
from meeting_memory.types.meeting import MeetingRef, validate_meeting_slug


class ArtifactOwnership(StrEnum):
    V2 = "v2"
    LEGACY = "legacy"
    FOREIGN = "foreign"


class ArtifactFieldOwner(StrEnum):
    CORE = "core"
    TRANSCRIPTION = "transcription"
    SPEAKERS = "speakers"
    BACKUP = "backup"


class MeetingJob(StrEnum):
    TRANSCRIPTION = "transcription"
    BACKUP = "backup"


class BackupUploadDisposition(StrEnum):
    COMPLETE = "complete"
    CANCELLED = "cancelled"
    PARTIAL = "partial"


@dataclass(frozen=True)
class MeetingArtifact:
    meeting: MeetingRef
    ownership: ArtifactOwnership
    transcript_path: Path
    audio_paths: tuple[Path, ...]
    transcription_status: MeetingJobState
    backup_status: MeetingJobState
    speaker_status: str

    @property
    def owned(self) -> bool:
        return self.ownership is not ArtifactOwnership.FOREIGN


@dataclass(frozen=True)
class BackupCompletionResult:
    """Outcome of comparing and recording one uploaded Backup snapshot."""

    completed: bool
    status: MeetingJobState
    captured_revision: str
    current_revision: str


@dataclass(frozen=True)
class LegacyUploadObject:
    """One private read-only legacy object stream and its original filename."""

    filename: str
    stream: BinaryIO

    def __post_init__(self) -> None:
        if Path(self.filename).name != self.filename or not self.filename:
            raise ValueError("legacy upload filename must be one path component")


@dataclass(frozen=True)
class LegacyBackupUpload:
    """Pinned legacy bytes crossing into the B2 adapter."""

    meeting_slug: str
    audio: tuple[LegacyUploadObject, ...]
    transcript: LegacyUploadObject

    def __post_init__(self) -> None:
        validate_meeting_slug(self.meeting_slug)
        if not self.audio:
            raise ValueError("legacy backup requires at least one audio object")


@dataclass(frozen=True)
class BackupSnapshotUpload:
    """Immutable file-backed Backup request crossing into the repo layer."""

    meeting_slug: str
    revision: str
    directory: Path
    directory_device: int
    directory_inode: int

    def __post_init__(self) -> None:
        validate_meeting_slug(self.meeting_slug)
        _validate_revision(self.revision)
        if self.directory_device < 0 or self.directory_inode <= 0:
            raise ValueError("backup snapshot directory identity is invalid")

    @property
    def audio_path(self) -> Path:
        return self.directory / "recording.m4a"

    @property
    def transcript_path(self) -> Path:
        return self.directory / "transcript.md"


@dataclass(frozen=True)
class BackupSnapshotUploadResult:
    """Provider-side progress only; durable state remains service-owned."""

    disposition: BackupUploadDisposition
    meeting_slug: str
    revision: str
    audio_key: str | None = None
    transcript_key: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, BackupUploadDisposition):
            raise TypeError("backup upload disposition must be BackupUploadDisposition")
        validate_meeting_slug(self.meeting_slug)
        _validate_revision(self.revision)
        expected_audio = f"meetings/{self.meeting_slug}/recording.m4a"
        expected_transcript = f"meetings/{self.meeting_slug}/transcript.md"
        if self.disposition is BackupUploadDisposition.COMPLETE:
            if self.audio_key != expected_audio or self.transcript_key != expected_transcript:
                raise ValueError("complete backup result requires both exact object keys")
        elif self.disposition is BackupUploadDisposition.PARTIAL:
            if self.audio_key != expected_audio or self.transcript_key is not None:
                raise ValueError("partial backup result requires only the exact audio key")
        elif self.audio_key is not None or self.transcript_key is not None:
            raise ValueError("cancelled backup result cannot claim uploaded objects")

    @property
    def pending_ready(self) -> bool:
        return self.disposition is not BackupUploadDisposition.COMPLETE


class BackupUploadCancellation:
    """Monotonic per-worker cancellation; re-enable requires a new instance."""

    def __init__(self) -> None:
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()


def _validate_revision(revision: str) -> None:
    if not isinstance(revision, str) or re.fullmatch(r"[0-9a-f]{64}", revision) is None:
        raise ValueError("backup revision must be 64 lowercase hexadecimal characters")

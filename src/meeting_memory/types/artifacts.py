"""Pure local-artifact ownership and state boundary data."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from meeting_memory.types.capabilities import MeetingJobState
from meeting_memory.types.meeting import MeetingRef


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

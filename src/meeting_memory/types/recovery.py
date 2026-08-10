"""Pure boundary data for indexed and legacy recording recovery."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from meeting_memory.types.meeting import MeetingMeta, PostCommitPolicy


class RecoveryOrigin(StrEnum):
    APP_STAGING = "app_staging"
    LEGACY_TEMP = "legacy_temp"


@dataclass(frozen=True)
class RecoveryPublication:
    """Persisted identity for a visible publication whose fsync was uncertain."""

    slug: str
    directory_device: int
    directory_inode: int
    audio_device: int
    audio_inode: int
    audio_size: int
    audio_sha256: str
    source_device: int
    source_inode: int
    source_size: int
    source_sha256: str
    policy: PostCommitPolicy


@dataclass(frozen=True)
class RecoveryIndexEntry:
    session_directory: Path
    source_path: Path
    index_path: Path | None
    meta: MeetingMeta
    origin: RecoveryOrigin
    session_device: int
    session_inode: int
    source_device: int | None = None
    source_inode: int | None = None
    source_size: int | None = None
    source_sha256: str | None = None
    publication: RecoveryPublication | None = None

    @property
    def wav_path(self) -> Path | None:
        return self.source_path if self.source_path.suffix.casefold() == ".wav" else None


@dataclass(frozen=True)
class LegacyDiscoveryState:
    """Explicit caller-owned once-only migration scan state."""

    completed: bool = False


@dataclass(frozen=True)
class LegacyDiscoveryResult:
    entries: tuple[RecoveryIndexEntry, ...]
    state: LegacyDiscoveryState

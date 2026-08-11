"""Thread-safe Backup admission and cancellation state."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Protocol

from meeting_memory.service.meeting_state import MeetingStateConflict, MeetingStateStore
from meeting_memory.service.runtime_files import RuntimeMeetingHandle
from meeting_memory.types.artifacts import (
    BackupSnapshotUpload,
    BackupSnapshotUploadResult,
    BackupUploadCancellation,
    MeetingJob,
)
from meeting_memory.types.capabilities import MeetingJobState


class RuntimeBackupClient(Protocol):
    def upload_backup_snapshot(
        self,
        request: BackupSnapshotUpload,
        *,
        cancellation: BackupUploadCancellation,
    ) -> BackupSnapshotUploadResult:
        raise NotImplementedError


class RuntimeBackupGate:
    def __init__(self, client_present: bool, allowed: Callable[[], bool]) -> None:
        self._allowed = allowed
        self._enabled = client_present
        self._lock = threading.Lock()
        self._tokens: dict[str, BackupUploadCancellation] = {}

    @property
    def enabled(self) -> bool:
        if not self._allowed():
            return False
        with self._lock:
            return self._enabled

    def set_enabled(self, enabled: bool, *, client_present: bool) -> None:
        with self._lock:
            self._enabled = enabled and client_present
            if not self._enabled:
                for token in self._tokens.values():
                    token.cancel()

    def register(self, meeting_slug: str) -> BackupUploadCancellation | None:
        if not self._allowed():
            return None
        with self._lock:
            if not self._enabled or meeting_slug in self._tokens:
                return None
            token = BackupUploadCancellation()
            self._tokens[meeting_slug] = token
            return token

    def release(self, meeting_slug: str, token: BackupUploadCancellation) -> None:
        with self._lock:
            if self._tokens.get(meeting_slug) is token:
                del self._tokens[meeting_slug]


def defer_paused_backup(state: MeetingStateStore, handle: RuntimeMeetingHandle) -> None:
    try:
        state.transition_job(
            handle.files.directory,
            MeetingJob.BACKUP,
            MeetingJobState.RUNNING,
            MeetingJobState.PENDING,
            expected_directory_identity=handle.directory_identity,
        )
    except (MeetingStateConflict, OSError, TypeError, ValueError):
        return

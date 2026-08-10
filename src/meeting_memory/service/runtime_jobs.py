"""Optional post-commit jobs for owned schema-v2 meetings."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from meeting_memory.service.backup_revision import capture_backup_snapshot
from meeting_memory.service.meeting_state import MeetingStateConflict, MeetingStateStore
from meeting_memory.service.runtime_files import (
    RuntimeMeetingHandle,
    bind_runtime_meeting_files,
    validate_runtime_meeting_handle,
)
from meeting_memory.service.runtime_transcription import (
    RuntimeTranscription,
    RuntimeTranscriptionClient,
)
from meeting_memory.types.artifacts import (
    BackupSnapshotUpload,
    BackupSnapshotUploadResult,
    BackupUploadCancellation,
    BackupUploadDisposition,
    MeetingJob,
)
from meeting_memory.types.capabilities import MeetingJobState
from meeting_memory.types.meeting import MeetingFiles

LOGGER = logging.getLogger(__name__)
EventSink = Callable[[object], None]
ThreadFactory = Callable[..., threading.Thread]


class RuntimeBackupClient(Protocol):
    """Upload one immutable snapshot without owning durable meeting state."""

    def upload_backup_snapshot(
        self,
        request: BackupSnapshotUpload,
        *,
        cancellation: BackupUploadCancellation,
    ) -> BackupSnapshotUploadResult:
        raise NotImplementedError


class RuntimeJobs:
    """Run independently optional jobs after local publication and notification."""

    def __init__(
        self,
        meetings_dir: Path,
        event_sink: EventSink,
        *,
        transcription_client: RuntimeTranscriptionClient | None = None,
        backup_client: RuntimeBackupClient | None = None,
        thread_factory: ThreadFactory = threading.Thread,
    ) -> None:
        self._state = MeetingStateStore(meetings_dir)
        self._backup_client = backup_client
        self._thread_factory = thread_factory
        self._transcription = (
            RuntimeTranscription(
                meetings_dir,
                event_sink,
                transcription_client,
                thread_factory,
            )
            if transcription_client is not None
            else None
        )
        self._backup_lock = threading.Lock()
        self._backup_enabled = backup_client is not None
        self._backup_tokens: dict[str, BackupUploadCancellation] = {}

    def launch_for_commit(
        self,
        files: MeetingFiles,
        *,
        transcription: bool,
        backup: bool,
    ) -> None:
        """Start requested jobs only after the caller has emitted RecordingCommitted."""

        handle = self._bind(files)
        if handle is None:
            return
        if transcription and self._transcription is not None:
            self._transcription.start(handle)
        if backup and self._backup_client is not None and self.backup_enabled:
            self._start(self._run_backup, handle)

    @property
    def backup_enabled(self) -> bool:
        with self._backup_lock:
            return self._backup_enabled

    def set_backup_enabled(self, enabled: bool) -> None:
        """Cancel current attempts monotonically; re-enable affects only new work."""

        with self._backup_lock:
            self._backup_enabled = enabled and self._backup_client is not None
            if not self._backup_enabled:
                for token in self._backup_tokens.values():
                    token.cancel()

    def retry_transcription(
        self,
        meeting: MeetingFiles | RuntimeMeetingHandle,
        *,
        resume_id: str | None = None,
    ) -> None:
        if self._transcription is None:
            return
        handle = self._bind(meeting)
        if handle is not None:
            self._transcription.retry(handle, resume_id)

    def retry_backup(self, meeting: MeetingFiles | RuntimeMeetingHandle) -> None:
        if self._backup_client is None or not self.backup_enabled:
            return
        handle = self._bind(meeting)
        if handle is None or not self._valid_backup_files(handle):
            return
        files = handle.files
        with self._backup_lock:
            if files.meta.slug in self._backup_tokens:
                return
        for expected in (MeetingJobState.FAILED, MeetingJobState.RUNNING):
            try:
                self._state.transition_job(
                    files.directory,
                    MeetingJob.BACKUP,
                    expected,
                    MeetingJobState.PENDING,
                    expected_directory_identity=handle.directory_identity,
                )
                break
            except MeetingStateConflict:
                continue
        self._start(self._run_backup, handle)

    def _start(
        self,
        callback: Callable[[RuntimeMeetingHandle], None],
        handle: RuntimeMeetingHandle,
    ) -> None:
        try:
            worker = self._thread_factory(target=callback, args=(handle,), daemon=True)
            worker.start()
        except Exception:
            LOGGER.exception("Could not start optional meeting job")

    def _run_backup(self, handle: RuntimeMeetingHandle) -> None:
        self._run_backup_attempt(handle, allow_revision_retry=True)

    def _run_backup_retry(self, handle: RuntimeMeetingHandle) -> None:
        self._run_backup_attempt(handle, allow_revision_retry=False)

    def _run_backup_attempt(
        self,
        handle: RuntimeMeetingHandle,
        *,
        allow_revision_retry: bool,
    ) -> None:
        if not self._valid_backup_files(handle):
            return
        files = handle.files
        client = self._backup_client
        token = self._register_backup_token(files.meta.slug)
        if client is None or token is None:
            return
        revision_changed = False
        try:
            self._state.transition_job(
                files.directory,
                MeetingJob.BACKUP,
                MeetingJobState.PENDING,
                MeetingJobState.RUNNING,
                expected_directory_identity=handle.directory_identity,
            )
        except MeetingStateConflict:
            self._release_backup_token(files.meta.slug, token)
            return
        except Exception:
            self._release_backup_token(files.meta.slug, token)
            LOGGER.exception("Could not claim Backup job")
            return

        try:
            with capture_backup_snapshot(
                files.directory,
                expected_directory_identity=handle.directory_identity,
            ) as snapshot:
                result = client.upload_backup_snapshot(
                    snapshot.upload_request(),
                    cancellation=token,
                )
                revision_changed = self._finish_backup(
                    handle,
                    snapshot.revision,
                    result,
                )
        except MeetingStateConflict:
            return
        except Exception:
            self._mark_backup_failed(handle)
        finally:
            self._release_backup_token(files.meta.slug, token)
        if revision_changed and allow_revision_retry and self.backup_enabled:
            self._start(self._run_backup_retry, handle)

    def _valid_backup_files(self, handle: RuntimeMeetingHandle) -> bool:
        try:
            validate_runtime_meeting_handle(self._state.meetings_dir, handle)
        except (OSError, TypeError, UnicodeError, ValueError):
            LOGGER.warning("Rejected invalid runtime Backup files")
            return False
        return True

    def _finish_backup(
        self,
        handle: RuntimeMeetingHandle,
        revision: str,
        result: BackupSnapshotUploadResult,
    ) -> bool:
        files = handle.files
        if result.meeting_slug != files.meta.slug or result.revision != revision:
            raise ValueError("Backup result does not match its captured meeting snapshot")
        if result.disposition is BackupUploadDisposition.COMPLETE:
            assert result.audio_key is not None and result.transcript_key is not None
            completion = self._state.complete_backup(
                files.directory,
                revision,
                result.audio_key,
                result.transcript_key,
                expected_directory_identity=handle.directory_identity,
            )
            return not completion.completed
        self._state.transition_job(
            files.directory,
            MeetingJob.BACKUP,
            MeetingJobState.RUNNING,
            MeetingJobState.PENDING,
            expected_directory_identity=handle.directory_identity,
        )
        return False

    def _mark_backup_failed(self, handle: RuntimeMeetingHandle) -> None:
        files = handle.files
        try:
            self._state.transition_job(
                files.directory,
                MeetingJob.BACKUP,
                MeetingJobState.RUNNING,
                MeetingJobState.FAILED,
                expected_directory_identity=handle.directory_identity,
            )
        except MeetingStateConflict:
            return
        except Exception:
            LOGGER.exception("Could not persist Backup failure")

    def _bind(
        self,
        meeting: MeetingFiles | RuntimeMeetingHandle,
    ) -> RuntimeMeetingHandle | None:
        try:
            if isinstance(meeting, RuntimeMeetingHandle):
                validate_runtime_meeting_handle(self._state.meetings_dir, meeting)
                return meeting
            return bind_runtime_meeting_files(self._state.meetings_dir, meeting)
        except (OSError, TypeError, UnicodeError, ValueError):
            LOGGER.warning("Rejected invalid runtime meeting files")
            return None

    def _register_backup_token(
        self,
        meeting_slug: str,
    ) -> BackupUploadCancellation | None:
        with self._backup_lock:
            if not self._backup_enabled or meeting_slug in self._backup_tokens:
                return None
            token = BackupUploadCancellation()
            self._backup_tokens[meeting_slug] = token
            return token

    def _release_backup_token(
        self,
        meeting_slug: str,
        token: BackupUploadCancellation,
    ) -> None:
        with self._backup_lock:
            if self._backup_tokens.get(meeting_slug) is token:
                del self._backup_tokens[meeting_slug]

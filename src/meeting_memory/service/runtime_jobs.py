"""Optional post-commit jobs for owned schema-v2 meetings."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path

from meeting_memory.service.backup_revision import capture_backup_snapshot
from meeting_memory.service.meeting_state import MeetingStateConflict, MeetingStateStore
from meeting_memory.service.runtime_backup_gate import (
    RuntimeBackupClient,
    RuntimeBackupGate,
    defer_paused_backup,
)
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
    BackupSnapshotUploadResult,
    BackupUploadCancellation,
    BackupUploadDisposition,
    MeetingJob,
)
from meeting_memory.types.capabilities import Capability, MeetingJobState
from meeting_memory.types.egress import EgressPaused
from meeting_memory.types.meeting import MeetingFiles

LOGGER = logging.getLogger(__name__)
EventSink = Callable[[object], None]
ThreadFactory = Callable[..., threading.Thread]


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
        capability_enabled: Callable[[Capability], bool] = lambda _capability: True,
    ) -> None:
        self._state = MeetingStateStore(meetings_dir)
        self._backup_client = backup_client
        self._thread_factory = thread_factory
        self._capability_enabled = capability_enabled
        self._transcription = (
            RuntimeTranscription(
                meetings_dir,
                event_sink,
                transcription_client,
                thread_factory,
                enabled=lambda: self.transcription_enabled,
            )
            if transcription_client is not None
            else None
        )
        self._backup_gate = RuntimeBackupGate(
            backup_client is not None,
            lambda: self._capability_enabled(Capability.BACKUP),
        )
        self._transcription_lock = threading.Lock()
        self._transcription_enabled = transcription_client is not None

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
        if transcription and self._transcription is not None and self.transcription_enabled:
            self._transcription.start(handle)
        if backup and self._backup_client is not None and self.backup_enabled:
            self._start(self._run_backup, handle)

    @property
    def backup_enabled(self) -> bool:
        return self._backup_gate.enabled

    def set_backup_enabled(self, enabled: bool) -> None:
        """Cancel current attempts monotonically; re-enable affects only new work."""

        self._backup_gate.set_enabled(
            enabled,
            client_present=self._backup_client is not None,
        )

    @property
    def transcription_enabled(self) -> bool:
        if not self._capability_enabled(Capability.TRANSCRIPTION):
            return False
        with self._transcription_lock:
            return self._transcription_enabled

    def set_transcription_enabled(self, enabled: bool) -> None:
        """Stop new claims/retries; an already-started provider request may finish."""

        with self._transcription_lock:
            self._transcription_enabled = enabled and self._transcription is not None

    def retry_transcription(
        self,
        meeting: MeetingFiles | RuntimeMeetingHandle,
        *,
        resume_id: str | None = None,
    ) -> None:
        if self._transcription is None or not self.transcription_enabled:
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
            self._backup_gate.release(files.meta.slug, token)
            return
        except Exception:
            self._backup_gate.release(files.meta.slug, token)
            LOGGER.exception("Could not claim Backup job")
            return

        try:
            with capture_backup_snapshot(
                files.directory,
                expected_directory_identity=handle.directory_identity,
            ) as snapshot:
                if not self.backup_enabled:
                    token.cancel()
                    defer_paused_backup(self._state, handle)
                    return
                result = client.upload_backup_snapshot(
                    snapshot.upload_request(),
                    cancellation=token,
                )
                revision_changed = self._finish_backup(
                    handle,
                    snapshot.revision,
                    result,
                )
        except EgressPaused:
            defer_paused_backup(self._state, handle)
            return
        except MeetingStateConflict:
            return
        except Exception:
            self._mark_backup_failed(handle)
        finally:
            self._backup_gate.release(files.meta.slug, token)
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
        return self._backup_gate.register(meeting_slug)

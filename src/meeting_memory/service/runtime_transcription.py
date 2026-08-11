"""Single-flight durable Transcription runtime for schema-v2 meetings."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import BinaryIO, Protocol

from meeting_memory.service.meeting_state import MeetingStateConflict, MeetingStateStore
from meeting_memory.service.runtime_files import (
    RuntimeMeetingHandle,
    bind_runtime_meeting_files,
    validate_runtime_meeting_handle,
)
from meeting_memory.service.transcript_state import TranscriptStateStore
from meeting_memory.service.transcription_audio import capture_transcription_audio
from meeting_memory.types.artifacts import MeetingJob
from meeting_memory.types.capabilities import MeetingJobState
from meeting_memory.types.egress import EgressPaused
from meeting_memory.types.events import TranscriptionFailed, TranscriptReady
from meeting_memory.types.meeting import MeetingFiles, MeetingRef
from meeting_memory.types.transcript import TranscriptResult

LOGGER = logging.getLogger(__name__)
EventSink = Callable[[object], None]
ThreadFactory = Callable[..., threading.Thread]


class RuntimeTranscriptionClient(Protocol):
    def submit(self, audio: BinaryIO) -> str:
        raise NotImplementedError

    def resume(self, job_id: str) -> TranscriptResult:
        raise NotImplementedError


class RuntimeTranscription:
    """Claim, submit or resume, and finish one provider job per meeting."""

    def __init__(
        self,
        meetings_dir: Path,
        event_sink: EventSink,
        client: RuntimeTranscriptionClient,
        thread_factory: ThreadFactory,
        enabled: Callable[[], bool] = lambda: True,
    ) -> None:
        self._state = MeetingStateStore(meetings_dir)
        self._transcripts = TranscriptStateStore(meetings_dir)
        self._event_sink = event_sink
        self._client = client
        self._thread_factory = thread_factory
        self._enabled = enabled
        self._lock = threading.Lock()
        self._active: set[str] = set()

    def start(self, meeting: MeetingFiles | RuntimeMeetingHandle) -> None:
        if not self._enabled():
            return
        handle = self._validated_handle(meeting)
        if handle is not None and self._reserve(handle.files.meta.slug):
            self._launch_reserved(handle, resume_id=None)

    def retry(
        self,
        meeting: MeetingFiles | RuntimeMeetingHandle,
        resume_id: str | None = None,
    ) -> None:
        if not self._enabled():
            return
        handle = self._validated_handle(meeting)
        if handle is None or not self._reserve(handle.files.meta.slug):
            return
        files = handle.files
        if resume_id is None:
            try:
                self._transcripts.prepare_retry(
                    files.directory,
                    expected_directory_identity=handle.directory_identity,
                )
            except MeetingStateConflict:
                self._release(files.meta.slug)
                return
            except Exception:
                self._release(files.meta.slug)
                LOGGER.exception("Could not prepare Transcription retry")
                return
        self._launch_reserved(handle, resume_id=resume_id)

    def _reserve(self, slug: str) -> bool:
        with self._lock:
            if slug in self._active:
                return False
            self._active.add(slug)
            return True

    def _launch_reserved(
        self,
        handle: RuntimeMeetingHandle,
        *,
        resume_id: str | None,
    ) -> None:
        callback = partial(self._run_guarded, resume_id=resume_id)
        try:
            worker = self._thread_factory(target=callback, args=(handle,), daemon=True)
            worker.start()
        except Exception:
            self._release(handle.files.meta.slug)
            LOGGER.exception("Could not start Transcription worker")

    def _run_guarded(
        self,
        handle: RuntimeMeetingHandle,
        *,
        resume_id: str | None,
    ) -> None:
        try:
            self._run(handle, resume_id=resume_id)
        finally:
            self._release(handle.files.meta.slug)

    def _run(self, handle: RuntimeMeetingHandle, *, resume_id: str | None) -> None:
        if not self._enabled():
            return
        files = handle.files
        if resume_id is None and not self._claim_pending(handle):
            return
        job_id = resume_id
        try:
            if job_id is None:
                with capture_transcription_audio(
                    self._state.meetings_dir,
                    files,
                    expected_directory_identity=handle.directory_identity,
                ) as audio:
                    if self._defer_if_disabled(handle, has_provider_id=False):
                        return
                    job_id = self._client.submit(audio)
                self._transcripts.record_job_id(
                    files.directory,
                    job_id,
                    expected_directory_identity=handle.directory_identity,
                )
            else:
                self._transcripts.record_job_id(
                    files.directory,
                    job_id,
                    expected_id=job_id,
                    expected_directory_identity=handle.directory_identity,
                )
            if self._defer_if_disabled(handle, has_provider_id=True):
                return
            transcript = self._client.resume(job_id)
            self._transcripts.succeed(
                files.directory,
                files.meta,
                transcript,
                expected_directory_identity=handle.directory_identity,
            )
        except EgressPaused:
            self._defer_if_disabled(handle, has_provider_id=job_id is not None)
            return
        except MeetingStateConflict:
            return
        except Exception:
            if self._record_failure(handle, job_id):
                self._event_sink(TranscriptionFailed(_meeting_ref(files)))
            return
        self._event_sink(TranscriptReady(_meeting_ref(files)))

    def _claim_pending(self, handle: RuntimeMeetingHandle) -> bool:
        files = handle.files
        try:
            self._state.transition_job(
                files.directory,
                MeetingJob.TRANSCRIPTION,
                MeetingJobState.PENDING,
                MeetingJobState.RUNNING,
                expected_directory_identity=handle.directory_identity,
            )
        except MeetingStateConflict:
            return False
        except Exception:
            LOGGER.exception("Could not claim Transcription job")
            return False
        return True

    def _defer_if_disabled(
        self,
        handle: RuntimeMeetingHandle,
        *,
        has_provider_id: bool,
    ) -> bool:
        if self._enabled():
            return False
        if has_provider_id:
            return True
        try:
            self._state.transition_job(
                handle.files.directory,
                MeetingJob.TRANSCRIPTION,
                MeetingJobState.RUNNING,
                MeetingJobState.PENDING,
                expected_directory_identity=handle.directory_identity,
            )
        except MeetingStateConflict:
            # Another worker already moved the durable job to a safe state.
            return True
        except Exception:
            LOGGER.warning("Could not defer paused Transcription job")
        return True

    def _record_failure(
        self,
        handle: RuntimeMeetingHandle,
        job_id: str | None,
    ) -> bool:
        files = handle.files
        try:
            self._transcripts.fail(
                files.directory,
                job_id,
                expected_directory_identity=handle.directory_identity,
            )
        except MeetingStateConflict:
            return False
        except Exception:
            LOGGER.exception("Could not persist Transcription failure")
            return False
        return True

    def _release(self, slug: str) -> None:
        with self._lock:
            self._active.discard(slug)

    def _validated_handle(
        self,
        meeting: MeetingFiles | RuntimeMeetingHandle,
    ) -> RuntimeMeetingHandle | None:
        try:
            if isinstance(meeting, RuntimeMeetingHandle):
                validate_runtime_meeting_handle(self._state.meetings_dir, meeting)
                return meeting
            return bind_runtime_meeting_files(self._state.meetings_dir, meeting)
        except (OSError, TypeError, UnicodeError, ValueError):
            LOGGER.warning("Rejected invalid runtime Transcription files")
            return None


def _meeting_ref(files: MeetingFiles) -> MeetingRef:
    return MeetingRef(files.meta.slug, files.meta.calendar_title, files.directory)

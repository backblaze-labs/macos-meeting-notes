"""Single-flight durable Transcription with an explicitly selected backend."""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import BinaryIO, Protocol

from meeting_memory.service.local_transcription import align_local_transcript
from meeting_memory.service.meeting_state import MeetingStateConflict
from meeting_memory.service.runtime_files import (
    RuntimeMeetingHandle,
    bind_runtime_meeting_files,
    validate_runtime_meeting_handle,
)
from meeting_memory.service.transcript_state import TranscriptStateStore
from meeting_memory.service.transcription_attempts import (
    TranscriptionSourceChanged,
    check_attempt_source,
    claim_attempt,
    defer_attempt,
    fail_changed_remote_source,
    stream_digest,
)
from meeting_memory.service.transcription_audio import capture_transcription_audio
from meeting_memory.types.egress import EgressPaused
from meeting_memory.types.events import TranscriptionFailed, TranscriptionProgress, TranscriptReady
from meeting_memory.types.local_transcription import (
    LocalModelsUnavailable,
    LocalTranscriptionCancelled,
    LocalTranscriptionError,
)
from meeting_memory.types.meeting import MeetingFiles, MeetingRef
from meeting_memory.types.transcript import TranscriptResult
from meeting_memory.types.transcription import TranscriptionProvider

LOGGER = logging.getLogger(__name__)


class RuntimeTranscriptionClient(Protocol):
    def submit(self, audio: BinaryIO) -> str:
        raise NotImplementedError

    def resume(self, job_id: str) -> TranscriptResult:
        raise NotImplementedError


class RuntimeTranscription:
    def __init__(
        self,
        meetings_dir: Path,
        event_sink: Callable[[object], None],
        client,
        thread_factory: Callable[..., threading.Thread],
        enabled: Callable[[], bool] = lambda: True,
        on_transcript_committed: Callable[[RuntimeMeetingHandle], None] = lambda _handle: None,
        *,
        provider: TranscriptionProvider = TranscriptionProvider.ASSEMBLYAI,
    ) -> None:
        self._meetings_dir = meetings_dir
        self._transcripts = TranscriptStateStore(meetings_dir)
        self._event_sink, self._client = event_sink, client
        self._closed = threading.Event()
        self._thread_factory = thread_factory
        self._enabled = lambda: not self._closed.is_set() and enabled()
        self._on_transcript_committed = on_transcript_committed
        self._provider = provider
        self._lock = threading.Lock()
        self._active: set[str] = set()

    def shutdown(self) -> None:
        with self._lock:
            if self._closed.is_set():
                return
            self._closed.set()
        close = getattr(self._client, "close", None)
        if close is not None:
            try:
                close()
            except Exception:
                LOGGER.warning("Could not close the local Transcription worker")

    def start(self, meeting: MeetingFiles | RuntimeMeetingHandle) -> None:
        if not self._enabled():
            return
        handle = self._validated_handle(meeting)
        if handle is not None and self._reserve(handle.files.meta.slug):
            self._launch_reserved(handle, resume_id=None)

    def retry(self, meeting, resume_id: str | None = None) -> None:
        if not self._enabled():
            return
        handle = self._validated_handle(meeting)
        if handle is None or not self._reserve(handle.files.meta.slug):
            return
        if self._provider is TranscriptionProvider.LOCAL:
            resume_id = None
        if resume_id is None:
            try:
                self._transcripts.prepare_retry(
                    handle.files.directory,
                    expected_directory_identity=handle.directory_identity,
                )
            except Exception:
                self._release(handle.files.meta.slug)
                return
        self._launch_reserved(handle, resume_id=resume_id)

    def _reserve(self, slug: str) -> bool:
        with self._lock:
            if slug in self._active:
                return False
            self._active.add(slug)
            return True

    def _launch_reserved(self, handle, *, resume_id):
        try:
            self._thread_factory(
                target=partial(self._run_guarded, resume_id=resume_id),
                args=(handle,),
                daemon=True,
            ).start()
        except Exception:
            self._release(handle.files.meta.slug)
            LOGGER.warning("Could not start Transcription worker")

    def _run_guarded(self, handle, *, resume_id):
        try:
            self._run(handle, resume_id=resume_id)
        finally:
            self._release(handle.files.meta.slug)

    def _run(self, handle, *, resume_id):
        if not self._enabled():
            return
        try:
            attempt = claim_attempt(self._meetings_dir, handle, self._provider, resume_id=resume_id)
        except TranscriptionSourceChanged as changed:
            try:
                summary, action = fail_changed_remote_source(
                    self._meetings_dir, handle, resume_id, changed
                )
            except Exception:
                return
            self._event_sink(TranscriptionFailed(_meeting_ref(handle.files), summary, action))
            return
        except Exception:
            return
        job_id = resume_id
        try:
            if self._provider is TranscriptionProvider.LOCAL:
                with self._capture(handle, attempt) as audio:
                    if not self._enabled():
                        raise LocalTranscriptionCancelled()
                    output = self._client.transcribe(
                        audio,
                        progress=lambda progress: self._event_sink(
                            TranscriptionProgress(_meeting_ref(handle.files), progress)
                        ),
                        cancelled=lambda: not self._enabled(),
                    )
                transcript = align_local_transcript(output, attempt_id=attempt.attempt_id)
            else:
                if job_id is None:
                    with self._capture(handle, attempt) as audio:
                        if not self._enabled():
                            raise EgressPaused("Transcription is paused")
                        job_id = self._client.submit(audio)
                self._transcripts.record_job_id(
                    handle.files.directory,
                    job_id,
                    expected_id=resume_id,
                    expected_directory_identity=handle.directory_identity,
                    expected_attempt=attempt,
                )
                if not self._enabled():
                    return
                result = self._client.resume(job_id)
                transcript = replace(result, provider=self._provider, attempt_id=attempt.attempt_id)
            if not self._enabled() and self._provider is TranscriptionProvider.LOCAL:
                raise LocalTranscriptionCancelled()
            self._transcripts.succeed(
                handle.files.directory,
                handle.files.meta,
                transcript,
                expected_directory_identity=handle.directory_identity,
                expected_attempt=attempt,
            )
        except (LocalModelsUnavailable, LocalTranscriptionCancelled) as exc:
            self._defer(handle, attempt)
            self._event_sink(TranscriptionFailed(_meeting_ref(handle.files), str(exc), exc.action))
            return
        except EgressPaused:
            if job_id is None:
                self._defer(handle, attempt)
            return
        except MeetingStateConflict:
            return
        except Exception as exc:
            summary, action = self._safe_failure(exc)
            try:
                self._transcripts.fail(
                    handle.files.directory,
                    job_id,
                    expected_directory_identity=handle.directory_identity,
                    expected_attempt=attempt,
                    summary=summary,
                    action=action,
                )
            except Exception:
                return
            self._event_sink(TranscriptionFailed(_meeting_ref(handle.files), summary, action))
            return
        try:
            self._on_transcript_committed(handle)
        except Exception:
            LOGGER.warning("Could not start Backup after transcript publication")
        self._event_sink(TranscriptReady(_meeting_ref(handle.files)))

    def _capture(self, handle, attempt):
        from contextlib import contextmanager

        @contextmanager
        def snapshot():
            with capture_transcription_audio(
                self._meetings_dir,
                handle.files,
                expected_directory_identity=handle.directory_identity,
            ) as audio:
                identity = attempt.audio_identity
                if (
                    identity is None
                    or os.fstat(audio.fileno()).st_size != identity.size
                    or stream_digest(audio.fileno(), identity.size) != identity.sha256
                ):
                    raise MeetingStateConflict("Source changed before transcription")
                check_attempt_source(self._meetings_dir, handle, attempt)
                audio.seek(0)
                yield audio

        return snapshot()

    def _defer(self, handle, attempt):
        try:
            defer_attempt(self._meetings_dir, handle, attempt)
        except Exception:
            LOGGER.warning("Could not defer paused Transcription")

    @staticmethod
    def _safe_failure(error):
        if isinstance(error, LocalTranscriptionError):
            return str(error), error.action
        return (
            "Transcription failed. Audio remains saved locally.",
            "Use Retry Pending or Failed Transcriptions to try again.",
        )

    def _release(self, slug):
        with self._lock:
            self._active.discard(slug)

    def _validated_handle(self, meeting):
        try:
            if isinstance(meeting, RuntimeMeetingHandle):
                validate_runtime_meeting_handle(self._meetings_dir, meeting)
                return meeting
            return bind_runtime_meeting_files(self._meetings_dir, meeting)
        except (OSError, TypeError, UnicodeError, ValueError):
            LOGGER.warning("Rejected invalid runtime Transcription files")
            return None


def _meeting_ref(files):
    return MeetingRef(files.meta.slug, files.meta.calendar_title, files.directory)

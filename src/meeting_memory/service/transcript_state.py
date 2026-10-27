"""Atomic transcript publication with provider/attempt and source-audio CAS."""

from __future__ import annotations

from pathlib import Path

from meeting_memory.service.markdown import (
    render_transcript_body,
    render_transcription_failure_body,
    safe_frontmatter_text,
)
from meeting_memory.service.meeting_document import (
    MeetingDocument,
    open_meeting_document,
    require_meeting_directory_identity,
    validate_meeting_document,
)
from meeting_memory.service.meeting_locks import meeting_lock
from meeting_memory.service.meeting_state import MeetingStateConflict
from meeting_memory.service.transcription_attempts import replace_reconciled, require_attempt
from meeting_memory.types.capabilities import MeetingJobState
from meeting_memory.types.meeting import MeetingDirectoryIdentity, MeetingMeta
from meeting_memory.types.transcript import TranscriptResult
from meeting_memory.types.transcription import TranscriptionAttempt, TranscriptionProvider

LEGACY_FAILURE_SENTINEL = "transcription-failed"


class TranscriptStateStore:
    def __init__(self, meetings_dir: Path) -> None:
        self.meetings_dir = meetings_dir.expanduser()

    def succeed(
        self,
        meeting_dir: Path,
        meta: MeetingMeta,
        transcript: TranscriptResult,
        *,
        expected_directory_identity: MeetingDirectoryIdentity | None = None,
        expected_attempt: TranscriptionAttempt | None = None,
    ) -> None:
        identifier = _optional_identifier(transcript.assemblyai_id)
        if transcript.error or (
            transcript.provider is TranscriptionProvider.ASSEMBLYAI and identifier is None
        ):
            raise ValueError("successful transcription requires a valid provider result")
        if expected_attempt is not None and (
            transcript.provider is not expected_attempt.provider
            or transcript.attempt_id != expected_attempt.attempt_id
        ):
            raise MeetingStateConflict("Transcript result belongs to another attempt")
        self._finish(
            meeting_dir,
            meta=meta,
            provider_job_id=identifier,
            updates={
                "transcription_status": "succeeded",
                "participants": list(transcript.participants),
                "speaker_status": "needs_review",
            },
            body=render_transcript_body(meta, transcript),
            expected_directory_identity=expected_directory_identity,
            expected_attempt=expected_attempt,
        )

    def fail(
        self,
        meeting_dir: Path,
        provider_job_id: str | None = None,
        *,
        expected_directory_identity: MeetingDirectoryIdentity | None = None,
        expected_attempt: TranscriptionAttempt | None = None,
        summary: str | None = None,
        action: str | None = None,
    ) -> None:
        self._finish(
            meeting_dir,
            meta=None,
            provider_job_id=_optional_identifier(provider_job_id),
            updates={
                "transcription_status": "failed",
                "participants": [],
                "speaker_status": "not_available",
            },
            body=render_transcription_failure_body(summary=summary, action=action),
            expected_directory_identity=expected_directory_identity,
            expected_attempt=expected_attempt,
        )

    def record_job_id(
        self,
        meeting_dir: Path,
        new_id: str,
        *,
        expected_id: str | None = None,
        expected_directory_identity: MeetingDirectoryIdentity | None = None,
        expected_attempt: TranscriptionAttempt | None = None,
    ) -> None:
        identifier = _optional_identifier(new_id)
        if identifier is None:
            raise ValueError("transcription provider job ID must be non-blank")
        if (
            expected_attempt is not None
            and expected_attempt.provider is not TranscriptionProvider.ASSEMBLYAI
        ):
            raise ValueError("Only AssemblyAI attempts may have a remote job ID")
        validate_meeting_document(self.meetings_dir, meeting_dir)
        with meeting_lock(self.meetings_dir, meeting_dir.name):
            with open_meeting_document(self.meetings_dir, meeting_dir) as document:
                _require_identity(document, expected_directory_identity, expected_attempt)
                _require_running(document)
                current_id = _optional_identifier(document.frontmatter.get("assemblyai_id"))
                if current_id == identifier:
                    return
                if current_id != _optional_identifier(expected_id):
                    raise MeetingStateConflict("The provider job was replaced")
                replace_reconciled(document, {"assemblyai_id": identifier})

    def prepare_retry(
        self,
        meeting_dir: Path,
        *,
        expected_directory_identity: MeetingDirectoryIdentity | None = None,
    ) -> None:
        validate_meeting_document(self.meetings_dir, meeting_dir)
        with meeting_lock(self.meetings_dir, meeting_dir.name):
            with open_meeting_document(self.meetings_dir, meeting_dir) as document:
                _require_identity(document, expected_directory_identity, None, require_owned=False)
                if document.frontmatter.get("transcription_status") not in {
                    "pending",
                    "running",
                    "failed",
                }:
                    raise MeetingStateConflict("Transcription is no longer retryable")
                updates = {"transcription_status": "pending", "assemblyai_id": None}
                if "transcription_attempt_id" in document.frontmatter:
                    updates["transcription_attempt_id"] = None
                    updates["transcription_provider"] = None
                    updates["transcription_audio_sha256"] = None
                    updates["transcription_audio_size"] = None
                replace_reconciled(document, updates)

    def _finish(
        self,
        meeting_dir: Path,
        *,
        meta: MeetingMeta | None,
        provider_job_id: str | None,
        updates: dict[str, object],
        body: str,
        expected_directory_identity: MeetingDirectoryIdentity | None,
        expected_attempt: TranscriptionAttempt | None,
    ) -> None:
        validate_meeting_document(self.meetings_dir, meeting_dir)
        with meeting_lock(self.meetings_dir, meeting_dir.name):
            with open_meeting_document(self.meetings_dir, meeting_dir) as document:
                _require_identity(document, expected_directory_identity, expected_attempt)
                _require_running(document)
                if meta is not None:
                    _validate_meta(document, meta)
                stored_id = _optional_identifier(document.frontmatter.get("assemblyai_id"))
                if stored_id and provider_job_id and stored_id != provider_job_id:
                    raise MeetingStateConflict("The provider job was replaced")
                local = (
                    expected_attempt is not None
                    and expected_attempt.provider is TranscriptionProvider.LOCAL
                )
                updates = {
                    **updates,
                    "assemblyai_id": None if local else provider_job_id or stored_id,
                }
                replace_reconciled(document, updates, body=body)


def _require_running(document):
    if document.frontmatter.get("transcription_status") != MeetingJobState.RUNNING.value:
        raise MeetingStateConflict("Transcription is no longer running")


def _validate_meta(document: MeetingDocument, meta: MeetingMeta) -> None:
    expected = {
        "id": meta.slug,
        "date": meta.started_at.isoformat(),
        "duration_minutes": meta.duration_minutes,
        "calendar_title": safe_frontmatter_text(meta.calendar_title),
    }
    mismatched = [key for key, value in expected.items() if document.frontmatter.get(key) != value]
    if mismatched:
        raise MeetingStateConflict(f"Transcription metadata changed: {', '.join(mismatched)}")


def _optional_identifier(value: object) -> str | None:
    text = value.strip() if isinstance(value, str) else ""
    return text if text and text != LEGACY_FAILURE_SENTINEL else None


def _require_identity(document, directory_identity, attempt, *, require_owned=True):
    try:
        require_meeting_directory_identity(document, directory_identity)
    except ValueError as exc:
        raise MeetingStateConflict(str(exc)) from exc
    if require_owned:
        require_attempt(document, attempt)

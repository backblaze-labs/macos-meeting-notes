"""Atomic transcript body and schema-v2 job completion updates."""

from __future__ import annotations

from pathlib import Path

from meeting_memory.service.frontmatter import merge_frontmatter_fields
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
from meeting_memory.types.capabilities import MeetingJobState
from meeting_memory.types.meeting import MeetingDirectoryIdentity, MeetingMeta
from meeting_memory.types.transcript import TranscriptResult

LEGACY_FAILURE_SENTINEL = "transcription-failed"


class TranscriptStateStore:
    """Finish Transcription without losing a concurrent Backup-owned update."""

    def __init__(self, meetings_dir: Path) -> None:
        self.meetings_dir = meetings_dir.expanduser()

    def succeed(
        self,
        meeting_dir: Path,
        meta: MeetingMeta,
        transcript: TranscriptResult,
        *,
        expected_directory_identity: MeetingDirectoryIdentity | None = None,
    ) -> None:
        identifier = transcript.assemblyai_id.strip()
        if not identifier or identifier == LEGACY_FAILURE_SENTINEL or transcript.error:
            raise ValueError("successful transcription requires a provider job ID and no error")
        self._finish(
            meeting_dir,
            meta=meta,
            provider_job_id=identifier,
            updates={
                "transcription_status": MeetingJobState.SUCCEEDED.value,
                "participants": list(transcript.participants),
                "speaker_status": "needs_review",
            },
            body=render_transcript_body(meta, transcript),
            expected_directory_identity=expected_directory_identity,
        )

    def fail(
        self,
        meeting_dir: Path,
        provider_job_id: str | None = None,
        *,
        expected_directory_identity: MeetingDirectoryIdentity | None = None,
    ) -> None:
        identifier = (provider_job_id or "").strip() or None
        if identifier == LEGACY_FAILURE_SENTINEL:
            identifier = None
        self._finish(
            meeting_dir,
            meta=None,
            provider_job_id=identifier,
            updates={
                "transcription_status": MeetingJobState.FAILED.value,
                "participants": [],
                "speaker_status": "not_available",
            },
            body=render_transcription_failure_body(),
            expected_directory_identity=expected_directory_identity,
        )

    def record_job_id(
        self,
        meeting_dir: Path,
        new_id: str,
        *,
        expected_id: str | None = None,
        expected_directory_identity: MeetingDirectoryIdentity | None = None,
    ) -> None:
        """CAS the provider ID while the durable Transcription job is running."""

        identifier = new_id.strip()
        if not identifier or identifier == LEGACY_FAILURE_SENTINEL:
            raise ValueError("transcription provider job ID must be non-blank")
        validate_meeting_document(self.meetings_dir, meeting_dir)
        with meeting_lock(self.meetings_dir, meeting_dir.name):
            with open_meeting_document(self.meetings_dir, meeting_dir) as document:
                _require_expected_identity(document, expected_directory_identity)
                current_status = str(document.frontmatter.get("transcription_status"))
                if current_status != MeetingJobState.RUNNING.value:
                    raise MeetingStateConflict(
                        f"transcription state is {current_status}, expected running"
                    )
                current_id = _optional_identifier(document.frontmatter.get("assemblyai_id"))
                expected = _optional_identifier(expected_id)
                if current_id == identifier:
                    return
                if current_id != expected:
                    raise MeetingStateConflict(
                        f"transcription provider job is {current_id}, expected {expected}"
                    )
                prospective = merge_frontmatter_fields(
                    document.text,
                    {"assemblyai_id": identifier},
                )
                if document.frontmatter.get("backup_status") == MeetingJobState.SUCCEEDED.value:
                    revision = document.backup_revision(prospective)
                    if revision != document.frontmatter.get("backup_uploaded_revision"):
                        prospective = merge_frontmatter_fields(
                            prospective,
                            {"backup_status": MeetingJobState.PENDING.value},
                        )
                document.replace_transcript(prospective)

    def prepare_retry(
        self,
        meeting_dir: Path,
        *,
        expected_directory_identity: MeetingDirectoryIdentity | None = None,
    ) -> None:
        """Atomically reset retryable Transcription state before a new submit."""

        validate_meeting_document(self.meetings_dir, meeting_dir)
        with meeting_lock(self.meetings_dir, meeting_dir.name):
            with open_meeting_document(self.meetings_dir, meeting_dir) as document:
                _require_expected_identity(document, expected_directory_identity)
                current_status = _job_state(
                    document.frontmatter.get("transcription_status")
                )
                if current_status not in {
                    MeetingJobState.PENDING,
                    MeetingJobState.RUNNING,
                    MeetingJobState.FAILED,
                }:
                    raise MeetingStateConflict(
                        f"transcription state is {current_status.value}, not retryable"
                    )
                updates = {
                    "transcription_status": MeetingJobState.PENDING.value,
                    "assemblyai_id": None,
                }
                prospective = merge_frontmatter_fields(document.text, updates)
                if prospective == document.text:
                    return
                if (
                    document.frontmatter.get("backup_status")
                    == MeetingJobState.SUCCEEDED.value
                    and document.backup_revision(prospective)
                    != document.frontmatter.get("backup_uploaded_revision")
                ):
                    prospective = merge_frontmatter_fields(
                        prospective,
                        {"backup_status": MeetingJobState.PENDING.value},
                    )
                document.replace_transcript(prospective)

    def _finish(
        self,
        meeting_dir: Path,
        *,
        meta: MeetingMeta | None,
        provider_job_id: str | None,
        updates: dict[str, object],
        body: str,
        expected_directory_identity: MeetingDirectoryIdentity | None,
    ) -> None:
        validate_meeting_document(self.meetings_dir, meeting_dir)
        with meeting_lock(self.meetings_dir, meeting_dir.name):
            with open_meeting_document(self.meetings_dir, meeting_dir) as document:
                _require_expected_identity(document, expected_directory_identity)
                self._finish_locked(document, meta, provider_job_id, updates, body)

    @staticmethod
    def _finish_locked(
        document: MeetingDocument,
        meta: MeetingMeta | None,
        provider_job_id: str | None,
        updates: dict[str, object],
        body: str,
    ) -> None:
        current = str(document.frontmatter.get("transcription_status"))
        if current != MeetingJobState.RUNNING.value:
            raise MeetingStateConflict(f"transcription state is {current}, expected running")
        if meta is not None:
            _validate_meta(document, meta)
        stored_id = _optional_identifier(document.frontmatter.get("assemblyai_id"))
        if stored_id and provider_job_id and stored_id != provider_job_id:
            raise MeetingStateConflict(
                f"transcription provider job is {stored_id}, not {provider_job_id}"
            )
        updates = {**updates, "assemblyai_id": provider_job_id or stored_id}
        prospective = _replace_body(
            merge_frontmatter_fields(document.text, updates),
            body,
        )
        if document.frontmatter.get("backup_status") == MeetingJobState.SUCCEEDED.value:
            revision = document.backup_revision(prospective)
            if revision != document.frontmatter.get("backup_uploaded_revision"):
                prospective = merge_frontmatter_fields(
                    prospective,
                    {"backup_status": MeetingJobState.PENDING.value},
                )
        document.replace_transcript(prospective)


def _replace_body(markdown: str, body: str) -> str:
    lines = markdown.splitlines(keepends=True)
    closing = next(
        index
        for index, line in enumerate(lines[1:], start=1)
        if line.rstrip("\r\n") == "---"
    )
    frontmatter = "".join(lines[: closing + 1]).rstrip("\r\n")
    return f"{frontmatter}\n\n{body.rstrip()}\n"


def _validate_meta(document: MeetingDocument, meta: MeetingMeta) -> None:
    frontmatter = document.frontmatter
    expected = {
        "id": meta.slug,
        "date": meta.started_at.isoformat(),
        "duration_minutes": meta.duration_minutes,
        "calendar_title": safe_frontmatter_text(meta.calendar_title),
    }
    mismatched = [key for key, value in expected.items() if frontmatter.get(key) != value]
    if mismatched:
        raise MeetingStateConflict(f"transcription metadata changed: {', '.join(mismatched)}")


def _optional_identifier(value: object) -> str | None:
    identifier = value.strip() if isinstance(value, str) else ""
    return identifier if identifier and identifier != LEGACY_FAILURE_SENTINEL else None


def _job_state(value: object) -> MeetingJobState:
    try:
        return MeetingJobState(str(value))
    except ValueError as exc:
        raise MeetingStateConflict(f"invalid transcription state: {value!r}") from exc


def _require_expected_identity(
    document: MeetingDocument,
    expected: MeetingDirectoryIdentity | None,
) -> None:
    try:
        require_meeting_directory_identity(document, expected)
    except ValueError as exc:
        raise MeetingStateConflict(str(exc)) from exc

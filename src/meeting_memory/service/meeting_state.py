"""Atomic schema-v2 frontmatter state updates with field ownership."""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

from meeting_memory.service.frontmatter import merge_frontmatter_fields
from meeting_memory.service.meeting_document import (
    MeetingDocument,
    open_meeting_document,
    validate_meeting_document,
)
from meeting_memory.service.meeting_locks import meeting_lock
from meeting_memory.service.meeting_state_fields import (
    changed_fields,
    validate_core_identity,
    validate_owned_fields,
)
from meeting_memory.types.artifacts import (
    ArtifactFieldOwner,
    BackupCompletionResult,
    MeetingJob,
)
from meeting_memory.types.capabilities import MeetingJobState

VALID_TRANSITIONS = {
    MeetingJobState.NOT_REQUESTED: frozenset({MeetingJobState.PENDING}),
    MeetingJobState.PENDING: frozenset({MeetingJobState.RUNNING}),
    MeetingJobState.RUNNING: frozenset(
        {MeetingJobState.SUCCEEDED, MeetingJobState.FAILED, MeetingJobState.PENDING}
    ),
    MeetingJobState.FAILED: frozenset({MeetingJobState.PENDING}),
    MeetingJobState.SUCCEEDED: frozenset(),
}


class MeetingStateError(RuntimeError):
    """Base class for a rejected durable-state update."""


class MeetingStateConflict(MeetingStateError):
    """The state no longer matches the caller's compare-and-set value."""


class InvalidMeetingTransition(MeetingStateError):
    """The requested job-state edge is not in the contract graph."""


class MeetingStateStore:
    """Merge one owner's fields without losing concurrent owners' updates."""

    def __init__(self, meetings_dir: Path) -> None:
        self.meetings_dir = meetings_dir.expanduser()

    def merge_fields(
        self,
        meeting_dir: Path,
        owner: ArtifactFieldOwner,
        updates: Mapping[str, object],
    ) -> dict[str, object]:
        self._validate_owned_fields(owner, updates)
        self._validate_reference(meeting_dir)
        with meeting_lock(self.meetings_dir, meeting_dir.name):
            with self._document(meeting_dir) as document:
                frontmatter = document.frontmatter
                self._validate_core_identity(owner, frontmatter, updates)
                written_updates = changed_fields(frontmatter, updates)
                if not written_updates:
                    return frontmatter.copy()
                if owner is not ArtifactFieldOwner.BACKUP:
                    written_updates = self._reconcile_backup(document, written_updates)
                self._write_updates(document, written_updates)
                return document.frontmatter.copy()

    def transition_job(
        self,
        meeting_dir: Path,
        job: MeetingJob,
        expected: MeetingJobState,
        target: MeetingJobState,
        updates: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        owner, state_field = _job_owner_and_field(job)
        owned_updates = dict(updates or {})
        self._validate_owned_fields(owner, owned_updates)
        _validate_transition(job, expected, target)
        self._validate_reference(meeting_dir)

        with meeting_lock(self.meetings_dir, meeting_dir.name):
            with self._document(meeting_dir) as document:
                frontmatter = document.frontmatter
                current = _state(frontmatter.get(state_field))
                if current is not expected:
                    raise MeetingStateConflict(
                        f"{job.value} state is {current.value}, expected {expected.value}"
                    )
                if (
                    job is MeetingJob.BACKUP
                    and expected is MeetingJobState.SUCCEEDED
                    and target is MeetingJobState.PENDING
                    and document.backup_revision()
                    == frontmatter.get("backup_uploaded_revision")
                ):
                    raise InvalidMeetingTransition(
                        "backup succeeded -> pending requires a changed content revision"
                    )
                written_updates = {**owned_updates, state_field: target.value}
                if job is MeetingJob.TRANSCRIPTION:
                    written_updates = self._reconcile_backup(document, written_updates)
                self._write_updates(document, written_updates)
                return document.frontmatter.copy()

    def complete_backup(
        self,
        meeting_dir: Path,
        revision: str,
        audio_key: str,
        transcript_key: str,
    ) -> BackupCompletionResult:
        """Atomically record a complete matching snapshot or return it to pending."""

        _validate_revision(revision)
        self._validate_reference(meeting_dir)
        with meeting_lock(self.meetings_dir, meeting_dir.name):
            with self._document(meeting_dir) as document:
                _validate_completion_keys(document.path.name, audio_key, transcript_key)
                current = _state(document.frontmatter.get("backup_status"))
                if current is not MeetingJobState.RUNNING:
                    raise MeetingStateConflict(
                        f"backup state is {current.value}, expected running"
                    )
                current_revision = document.backup_revision()
                if revision != current_revision:
                    self._write_updates(
                        document,
                        {"backup_status": MeetingJobState.PENDING.value},
                    )
                    return BackupCompletionResult(
                        False,
                        MeetingJobState.PENDING,
                        revision,
                        current_revision,
                    )
                self._write_updates(
                    document,
                    {
                        "backup_status": MeetingJobState.SUCCEEDED.value,
                        "b2_audio": audio_key,
                        "b2_transcript": transcript_key,
                        "backup_uploaded_revision": revision,
                    },
                )
                return BackupCompletionResult(
                    True,
                    MeetingJobState.SUCCEEDED,
                    revision,
                    current_revision,
                )

    def confirm_speakers(
        self,
        meeting_dir: Path,
        aliases: Mapping[str, str],
        *,
        expected_status: str | None = None,
    ) -> Path:
        """Atomically relabel one schema-v2 transcript under its meeting lock."""

        from meeting_memory.service.speaker_state import confirm_v2_speakers

        return confirm_v2_speakers(
            self.meetings_dir,
            meeting_dir,
            aliases,
            expected_status=expected_status,
        )

    def _validate_reference(self, meeting_dir: Path) -> None:
        try:
            validate_meeting_document(self.meetings_dir, meeting_dir)
        except (OSError, UnicodeError, ValueError) as exc:
            raise MeetingStateError(str(exc)) from exc

    @staticmethod
    def _write_updates(
        document: MeetingDocument,
        updates: Mapping[str, object],
    ) -> None:
        document.replace_transcript(merge_frontmatter_fields(document.text, updates))

    @staticmethod
    def _reconcile_backup(
        document: MeetingDocument,
        updates: dict[str, object],
    ) -> dict[str, object]:
        frontmatter = document.frontmatter
        if frontmatter.get("backup_status") != MeetingJobState.SUCCEEDED.value:
            return updates
        prospective = merge_frontmatter_fields(document.text, updates)
        revision = document.backup_revision(prospective)
        if revision == frontmatter.get("backup_uploaded_revision"):
            return updates
        return {**updates, "backup_status": MeetingJobState.PENDING.value}

    @staticmethod
    def _validate_owned_fields(
        owner: ArtifactFieldOwner, updates: Mapping[str, object]
    ) -> None:
        try:
            validate_owned_fields(owner, updates)
        except ValueError as exc:
            raise MeetingStateError(str(exc)) from exc

    @staticmethod
    def _validate_core_identity(
        owner: ArtifactFieldOwner,
        current: Mapping[str, object],
        updates: Mapping[str, object],
    ) -> None:
        try:
            validate_core_identity(owner, current, updates)
        except ValueError as exc:
            raise MeetingStateError(str(exc)) from exc

    @contextmanager
    def _document(self, meeting_dir: Path) -> Iterator[MeetingDocument]:
        manager = open_meeting_document(self.meetings_dir, meeting_dir)
        try:
            document = manager.__enter__()
        except (OSError, UnicodeError, ValueError) as exc:
            raise MeetingStateError(str(exc)) from exc
        try:
            yield document
        finally:
            manager.__exit__(None, None, None)


def _job_owner_and_field(job: MeetingJob) -> tuple[ArtifactFieldOwner, str]:
    if job is MeetingJob.TRANSCRIPTION:
        return ArtifactFieldOwner.TRANSCRIPTION, "transcription_status"
    return ArtifactFieldOwner.BACKUP, "backup_status"


def _validate_transition(
    job: MeetingJob,
    expected: MeetingJobState,
    target: MeetingJobState,
) -> None:
    if job is MeetingJob.TRANSCRIPTION and target in {
        MeetingJobState.SUCCEEDED,
        MeetingJobState.FAILED,
    }:
        raise InvalidMeetingTransition(
            "transcription completion must use TranscriptStateStore"
        )
    if job is MeetingJob.BACKUP and target is MeetingJobState.SUCCEEDED:
        raise InvalidMeetingTransition("backup success must use complete_backup")
    allowed = set(VALID_TRANSITIONS[expected])
    if job is MeetingJob.BACKUP and expected is MeetingJobState.SUCCEEDED:
        allowed.add(MeetingJobState.PENDING)
    if target not in allowed:
        raise InvalidMeetingTransition(
            f"invalid {job.value} transition: {expected.value} -> {target.value}"
        )


def _state(value: object) -> MeetingJobState:
    try:
        return MeetingJobState(str(value))
    except ValueError as exc:
        raise MeetingStateError(f"invalid stored meeting job state: {value!r}") from exc


def _validate_revision(revision: str) -> None:
    if not isinstance(revision, str) or re.fullmatch(r"[0-9a-f]{64}", revision) is None:
        raise ValueError("backup revision must be 64 lowercase hexadecimal characters")


def _validate_completion_keys(slug: str, audio_key: str, transcript_key: str) -> None:
    expected_audio = f"meetings/{slug}/recording.m4a"
    expected_transcript = f"meetings/{slug}/transcript.md"
    if audio_key != expected_audio:
        raise ValueError(f"backup audio key must be {expected_audio}")
    if transcript_key != expected_transcript:
        raise ValueError(f"backup transcript key must be {expected_transcript}")

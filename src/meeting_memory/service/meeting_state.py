"""Atomic schema-v2 frontmatter state updates with field ownership."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from meeting_memory.service.atomic_io import atomic_replace_text
from meeting_memory.service.backup_revision import (
    compute_backup_revision,
    compute_backup_revision_with_transcript,
)
from meeting_memory.service.frontmatter import merge_frontmatter_fields
from meeting_memory.service.meeting_locks import meeting_lock
from meeting_memory.service.meeting_paths import (
    ValidatedMeetingDirectory,
    validate_state_meeting_directory,
)
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
        validated = self._validate_path(meeting_dir)
        meeting_dir = validated.path
        self._validate_owned_fields(owner, updates)
        self._validate_core_identity(owner, validated.frontmatter, updates)
        with meeting_lock(self.meetings_dir, meeting_dir.name):
            locked = self._validate_path(meeting_dir)
            text, frontmatter = locked.text, locked.frontmatter
            self._validate_core_identity(owner, frontmatter, updates)
            written_updates = changed_fields(frontmatter, updates)
            if not written_updates:
                return frontmatter.copy()
            if owner is not ArtifactFieldOwner.BACKUP:
                written_updates = self._reconcile_backup(
                    meeting_dir, text, frontmatter, written_updates
                )
            self._write_updates(meeting_dir, text, frontmatter, written_updates)
            return frontmatter.copy()

    def transition_job(
        self,
        meeting_dir: Path,
        job: MeetingJob,
        expected: MeetingJobState,
        target: MeetingJobState,
        updates: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        meeting_dir = self._validate_path(meeting_dir).path
        owner, state_field = _job_owner_and_field(job)
        owned_updates = dict(updates or {})
        self._validate_owned_fields(owner, owned_updates)
        _validate_transition(job, expected, target)

        with meeting_lock(self.meetings_dir, meeting_dir.name):
            locked = self._validate_path(meeting_dir)
            text, frontmatter = locked.text, locked.frontmatter
            current = _state(frontmatter.get(state_field))
            if current is not expected:
                raise MeetingStateConflict(
                    f"{job.value} state is {current.value}, expected {expected.value}"
                )
            if (
                job is MeetingJob.BACKUP
                and expected is MeetingJobState.SUCCEEDED
                and target is MeetingJobState.PENDING
            ):
                current_revision = compute_backup_revision(
                    meeting_dir / "recording.m4a", meeting_dir / "transcript.md"
                )
                if current_revision == frontmatter.get("backup_uploaded_revision"):
                    raise InvalidMeetingTransition(
                        "backup succeeded -> pending requires a changed content revision"
                    )
            written_updates = {**owned_updates, state_field: target.value}
            if job is MeetingJob.TRANSCRIPTION:
                written_updates = self._reconcile_backup(
                    meeting_dir, text, frontmatter, written_updates
                )
            self._write_updates(meeting_dir, text, frontmatter, written_updates)
            return frontmatter.copy()

    def complete_backup(
        self,
        meeting_dir: Path,
        revision: str,
        audio_key: str,
        transcript_key: str,
    ) -> BackupCompletionResult:
        """Atomically record a complete matching snapshot or return it to pending."""

        meeting_dir = self._validate_path(meeting_dir).path
        _validate_completion_inputs(revision, audio_key, transcript_key)
        with meeting_lock(self.meetings_dir, meeting_dir.name):
            locked = self._validate_path(meeting_dir)
            text, frontmatter = locked.text, locked.frontmatter
            current = _state(frontmatter.get("backup_status"))
            if current is not MeetingJobState.RUNNING:
                raise MeetingStateConflict(
                    f"backup state is {current.value}, expected running"
                )
            current_revision = compute_backup_revision(
                meeting_dir / "recording.m4a", meeting_dir / "transcript.md"
            )
            if revision != current_revision:
                self._write_updates(
                    meeting_dir,
                    text,
                    frontmatter,
                    {"backup_status": MeetingJobState.PENDING.value},
                )
                return BackupCompletionResult(
                    completed=False,
                    status=MeetingJobState.PENDING,
                    captured_revision=revision,
                    current_revision=current_revision,
                )

            self._write_updates(
                meeting_dir,
                text,
                frontmatter,
                {
                    "backup_status": MeetingJobState.SUCCEEDED.value,
                    "b2_audio": audio_key.strip(),
                    "b2_transcript": transcript_key.strip(),
                    "backup_uploaded_revision": revision,
                },
            )
            return BackupCompletionResult(
                completed=True,
                status=MeetingJobState.SUCCEEDED,
                captured_revision=revision,
                current_revision=current_revision,
            )

    @staticmethod
    def _write_updates(
        meeting_dir: Path,
        text: str,
        frontmatter: dict[str, object],
        updates: Mapping[str, object],
    ) -> None:
        atomic_replace_text(
            meeting_dir / "transcript.md", merge_frontmatter_fields(text, updates)
        )
        frontmatter.update(updates)

    @staticmethod
    def _reconcile_backup(
        meeting_dir: Path,
        text: str,
        frontmatter: dict[str, object],
        updates: dict[str, object],
    ) -> dict[str, object]:
        if frontmatter.get("backup_status") != MeetingJobState.SUCCEEDED.value:
            return updates
        prospective = merge_frontmatter_fields(text, updates)
        revision = compute_backup_revision_with_transcript(
            meeting_dir / "recording.m4a", prospective
        )
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

    def _validate_path(self, meeting_dir: Path) -> ValidatedMeetingDirectory:
        try:
            return validate_state_meeting_directory(self.meetings_dir, meeting_dir)
        except (OSError, UnicodeError, ValueError) as exc:
            raise MeetingStateError(str(exc)) from exc


def _job_owner_and_field(job: MeetingJob) -> tuple[ArtifactFieldOwner, str]:
    if job is MeetingJob.TRANSCRIPTION:
        return ArtifactFieldOwner.TRANSCRIPTION, "transcription_status"
    return ArtifactFieldOwner.BACKUP, "backup_status"


def _validate_transition(
    job: MeetingJob,
    expected: MeetingJobState,
    target: MeetingJobState,
) -> None:
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


def _validate_completion_inputs(revision: str, audio_key: str, transcript_key: str) -> None:
    if not isinstance(revision, str) or re.fullmatch(r"[0-9a-f]{64}", revision) is None:
        raise ValueError("backup revision must be 64 lowercase hexadecimal characters")
    if not isinstance(audio_key, str) or not audio_key.strip():
        raise ValueError("backup audio key must not be blank")
    if not isinstance(transcript_key, str) or not transcript_key.strip():
        raise ValueError("backup transcript key must not be blank")

"""Tests for reopening stale successful Backup state in the same write."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from meeting_memory.service.backup_revision import compute_backup_revision
from meeting_memory.service.meeting_document import MeetingDocument
from meeting_memory.service.meeting_state import MeetingStateError, MeetingStateStore
from meeting_memory.service.meeting_store import MeetingStore
from meeting_memory.service.storage import read_frontmatter
from meeting_memory.types.artifacts import ArtifactFieldOwner, MeetingJob
from meeting_memory.types.capabilities import MeetingJobState
from meeting_memory.types.meeting import MeetingMeta, PostCommitPolicy


@pytest.mark.parametrize(
    ("owner", "updates"),
    [
        (ArtifactFieldOwner.CORE, {"calendar_title": "Changed"}),
        (ArtifactFieldOwner.TRANSCRIPTION, {"participants": ["Speaker A"]}),
        (ArtifactFieldOwner.SPEAKERS, {"speaker_candidates": ["Alex"]}),
    ],
)
def test_meaningful_owner_merge_reopens_backup_in_same_atomic_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    owner: ArtifactFieldOwner,
    updates: dict[str, object],
) -> None:
    meeting, store = _completed_backup(tmp_path)
    writes: list[str] = []
    real_replace = MeetingDocument.replace_transcript

    def observe(document: MeetingDocument, text: str) -> None:
        writes.append(text)
        real_replace(document, text)

    monkeypatch.setattr(MeetingDocument, "replace_transcript", observe)
    store.merge_fields(meeting, owner, updates)

    assert len(writes) == 1
    frontmatter = read_frontmatter(meeting / "transcript.md")
    assert frontmatter["backup_status"] == "pending"
    assert all(frontmatter[key] == value for key, value in updates.items())


def test_transcription_transition_reopens_successful_backup(tmp_path: Path) -> None:
    meeting, store = _completed_backup(tmp_path)

    store.transition_job(
        meeting,
        MeetingJob.TRANSCRIPTION,
        MeetingJobState.PENDING,
        MeetingJobState.RUNNING,
    )

    frontmatter = read_frontmatter(meeting / "transcript.md")
    assert frontmatter["transcription_status"] == "running"
    assert frontmatter["backup_status"] == "pending"


def test_noop_owner_merge_does_not_write_or_reopen(tmp_path: Path, monkeypatch) -> None:
    meeting, store = _completed_backup(tmp_path)
    monkeypatch.setattr(
        MeetingDocument,
        "replace_transcript",
        lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected write")),
    )

    store.merge_fields(meeting, ArtifactFieldOwner.CORE, {"calendar_title": "State"})

    assert read_frontmatter(meeting / "transcript.md")["backup_status"] == "succeeded"


def test_backup_bookkeeping_merge_is_reserved_for_completion(tmp_path: Path) -> None:
    meeting, store = _completed_backup(tmp_path)
    before = (meeting / "transcript.md").read_bytes()

    with pytest.raises(MeetingStateError, match="does not own"):
        store.merge_fields(meeting, ArtifactFieldOwner.BACKUP, {"b2_audio": "new-key"})

    assert read_frontmatter(meeting / "transcript.md")["backup_status"] == "succeeded"
    assert (meeting / "transcript.md").read_bytes() == before


def _completed_backup(tmp_path: Path) -> tuple[Path, MeetingStateStore]:
    audio = tmp_path / "staged.m4a"
    audio.write_bytes(b"audio")
    meeting = MeetingStore(tmp_path / "meetings").commit(
        audio,
        MeetingMeta(
            slug="2026-08-07_12-00_state",
            started_at=datetime(2026, 8, 7, 12, 0, tzinfo=UTC),
            calendar_title="State",
        ),
        PostCommitPolicy(transcription=True, backup=True),
    ).directory
    store = MeetingStateStore(tmp_path / "meetings")
    store.transition_job(
        meeting, MeetingJob.BACKUP, MeetingJobState.PENDING, MeetingJobState.RUNNING
    )
    revision = compute_backup_revision(meeting / "recording.m4a", meeting / "transcript.md")
    prefix = f"meetings/{meeting.name}"
    store.complete_backup(
        meeting,
        revision,
        f"{prefix}/recording.m4a",
        f"{prefix}/transcript.md",
    )
    return meeting, store

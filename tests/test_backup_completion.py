"""Tests for atomically completing a matching Backup snapshot."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from meeting_memory.service.backup_revision import compute_backup_revision
from meeting_memory.service.meeting_state import (
    InvalidMeetingTransition,
    MeetingStateConflict,
    MeetingStateStore,
)
from meeting_memory.service.meeting_store import MeetingStore
from meeting_memory.service.storage import read_frontmatter
from meeting_memory.types.artifacts import MeetingJob
from meeting_memory.types.capabilities import MeetingJobState
from meeting_memory.types.meeting import MeetingMeta, PostCommitPolicy


@pytest.mark.parametrize(
    ("revision", "audio_key", "transcript_key"),
    [
        ("", "audio", "transcript"),
        ("A" * 64, "audio", "transcript"),
        ("0" * 63, "audio", "transcript"),
        ("0" * 64, "", "transcript"),
        ("0" * 64, "audio", "   "),
    ],
)
def test_complete_backup_rejects_invalid_inputs(
    tmp_path: Path,
    revision: str,
    audio_key: str,
    transcript_key: str,
) -> None:
    meeting, store = _running_backup(tmp_path)

    with pytest.raises(ValueError):
        store.complete_backup(meeting, revision, audio_key, transcript_key)

    assert read_frontmatter(meeting / "transcript.md")["backup_status"] == "running"


def test_generic_transition_cannot_claim_backup_success(tmp_path: Path) -> None:
    meeting, store = _running_backup(tmp_path)

    with pytest.raises(InvalidMeetingTransition, match="complete_backup"):
        store.transition_job(
            meeting,
            MeetingJob.BACKUP,
            MeetingJobState.RUNNING,
            MeetingJobState.SUCCEEDED,
        )


def test_complete_backup_stale_revision_returns_to_pending_without_claim(tmp_path: Path) -> None:
    meeting, store = _running_backup(tmp_path)

    result = store.complete_backup(meeting, "0" * 64, "audio-key", "transcript-key")

    frontmatter = read_frontmatter(meeting / "transcript.md")
    assert not result.completed
    assert result.status is MeetingJobState.PENDING
    assert result.current_revision != result.captured_revision
    assert frontmatter["backup_status"] == "pending"
    assert frontmatter["b2_audio"] is None
    assert frontmatter["b2_transcript"] is None
    assert frontmatter["backup_uploaded_revision"] is None


def test_complete_backup_records_only_matching_snapshot(tmp_path: Path) -> None:
    meeting, store = _running_backup(tmp_path)
    revision = compute_backup_revision(meeting / "recording.m4a", meeting / "transcript.md")

    result = store.complete_backup(meeting, revision, " audio-key ", " transcript-key ")

    frontmatter = read_frontmatter(meeting / "transcript.md")
    assert result.completed
    assert result.status is MeetingJobState.SUCCEEDED
    assert result.current_revision == revision
    assert frontmatter["backup_status"] == "succeeded"
    assert frontmatter["b2_audio"] == "audio-key"
    assert frontmatter["b2_transcript"] == "transcript-key"
    assert frontmatter["backup_uploaded_revision"] == revision

    with pytest.raises(MeetingStateConflict):
        store.complete_backup(meeting, revision, "audio-key", "transcript-key")


def _running_backup(tmp_path: Path) -> tuple[Path, MeetingStateStore]:
    audio = tmp_path / "staged.m4a"
    audio.write_bytes(b"audio")
    meeting = MeetingStore(tmp_path / "meetings").commit(
        audio,
        MeetingMeta(
            slug="2026-08-07_11-00_backup",
            started_at=datetime(2026, 8, 7, 11, 0, tzinfo=UTC),
        ),
        PostCommitPolicy(backup=True),
    ).directory
    store = MeetingStateStore(tmp_path / "meetings")
    store.transition_job(
        meeting, MeetingJob.BACKUP, MeetingJobState.PENDING, MeetingJobState.RUNNING
    )
    return meeting, store

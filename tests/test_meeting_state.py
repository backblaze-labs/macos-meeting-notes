"""Tests for per-owner atomic job-state changes."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

from meeting_memory.service.backup_revision import compute_backup_revision
from meeting_memory.service.meeting_state import (
    InvalidMeetingTransition,
    MeetingStateConflict,
    MeetingStateError,
    MeetingStateStore,
)
from meeting_memory.service.meeting_store import MeetingStore
from meeting_memory.service.storage import read_frontmatter
from meeting_memory.types.artifacts import ArtifactFieldOwner, MeetingJob
from meeting_memory.types.capabilities import MeetingJobState
from meeting_memory.types.meeting import MeetingMeta, PostCommitPolicy


def test_valid_and_invalid_job_transitions(tmp_path: Path) -> None:
    meeting = _meeting(tmp_path)
    store = MeetingStateStore(tmp_path / "meetings")

    store.transition_job(
        meeting,
        MeetingJob.TRANSCRIPTION,
        MeetingJobState.PENDING,
        MeetingJobState.RUNNING,
        {"assemblyai_id": "tx-123"},
    )
    store.transition_job(
        meeting,
        MeetingJob.TRANSCRIPTION,
        MeetingJobState.RUNNING,
        MeetingJobState.SUCCEEDED,
    )

    with pytest.raises(InvalidMeetingTransition):
        store.transition_job(
            meeting,
            MeetingJob.TRANSCRIPTION,
            MeetingJobState.SUCCEEDED,
            MeetingJobState.PENDING,
        )
    store.transition_job(
        meeting,
        MeetingJob.BACKUP,
        MeetingJobState.PENDING,
        MeetingJobState.RUNNING,
    )
    with pytest.raises(InvalidMeetingTransition):
        store.transition_job(
            meeting,
            MeetingJob.BACKUP,
            MeetingJobState.RUNNING,
            MeetingJobState.SUCCEEDED,
        )


def test_compare_and_set_rejects_stale_expected_state(tmp_path: Path) -> None:
    meeting = _meeting(tmp_path)
    store = MeetingStateStore(tmp_path / "meetings")
    store.transition_job(
        meeting, MeetingJob.BACKUP, MeetingJobState.PENDING, MeetingJobState.RUNNING
    )

    with pytest.raises(MeetingStateConflict):
        store.transition_job(
            meeting, MeetingJob.BACKUP, MeetingJobState.PENDING, MeetingJobState.RUNNING
        )


def test_concurrent_owner_merges_preserve_each_other(tmp_path: Path) -> None:
    meeting = _meeting(tmp_path)
    store = MeetingStateStore(tmp_path / "meetings")
    barrier = threading.Barrier(2)

    def transcription_update() -> None:
        barrier.wait()
        store.merge_fields(
            meeting,
            ArtifactFieldOwner.TRANSCRIPTION,
            {"assemblyai_id": "tx-concurrent", "participants": ["Speaker A"]},
        )

    def backup_update() -> None:
        barrier.wait()
        store.merge_fields(
            meeting,
            ArtifactFieldOwner.BACKUP,
            {"b2_audio": "meetings/example/recording.m4a"},
        )

    threads = [
        threading.Thread(target=transcription_update),
        threading.Thread(target=backup_update),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    frontmatter = read_frontmatter(meeting / "transcript.md")
    assert frontmatter["assemblyai_id"] == "tx-concurrent"
    assert frontmatter["participants"] == ["Speaker A"]
    assert frontmatter["b2_audio"] == "meetings/example/recording.m4a"


def test_owner_cannot_write_another_owner_or_bypass_state_graph(tmp_path: Path) -> None:
    meeting = _meeting(tmp_path)
    store = MeetingStateStore(tmp_path / "meetings")

    with pytest.raises(MeetingStateError):
        store.merge_fields(meeting, ArtifactFieldOwner.BACKUP, {"assemblyai_id": "wrong"})
    with pytest.raises(MeetingStateError):
        store.merge_fields(meeting, ArtifactFieldOwner.BACKUP, {"backup_status": "succeeded"})


def test_backup_owner_merge_does_not_change_content_revision(tmp_path: Path) -> None:
    meeting = _meeting(tmp_path)
    store = MeetingStateStore(tmp_path / "meetings")
    before = compute_backup_revision(meeting / "recording.m4a", meeting / "transcript.md")

    store.merge_fields(
        meeting,
        ArtifactFieldOwner.BACKUP,
        {"b2_audio": "key", "backup_uploaded_revision": "a" * 64},
    )

    after = compute_backup_revision(meeting / "recording.m4a", meeting / "transcript.md")
    assert after == before


def _meeting(tmp_path: Path) -> Path:
    audio = tmp_path / "staged.m4a"
    audio.write_bytes(b"audio")
    files = MeetingStore(tmp_path / "meetings").commit(
        audio,
        MeetingMeta(
            slug="2026-08-07_10-00_state",
            started_at=datetime(2026, 8, 7, 10, 0, tzinfo=UTC),
            calendar_title="State",
        ),
        PostCommitPolicy(transcription=True, backup=True),
    )
    return files.directory

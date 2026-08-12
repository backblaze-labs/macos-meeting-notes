"""Locked schema-v2 speaker/body transaction tests."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

from meeting_memory.service.backup_revision import compute_backup_revision
from meeting_memory.service.meeting_state import MeetingStateConflict, MeetingStateStore
from meeting_memory.service.meeting_store import MeetingStore
from meeting_memory.service.storage import read_frontmatter
from meeting_memory.service.transcript_review import confirm_speaker_aliases
from meeting_memory.service.transcript_state import TranscriptStateStore
from meeting_memory.types.artifacts import ArtifactFieldOwner, MeetingJob
from meeting_memory.types.capabilities import MeetingJobState
from meeting_memory.types.meeting import MeetingMeta, PostCommitPolicy
from meeting_memory.types.transcript import TranscriptResult, TranscriptSegment


def test_v2_confirmation_uses_actual_lines_and_reconciles_backup(tmp_path: Path) -> None:
    meeting, _state = _reviewable_meeting(
        tmp_path,
        complete_backup=True,
        metadata_participants=("Metadata Phantom",),
    )

    confirm_speaker_aliases(meeting, {"Speaker A": "Alex", "Speaker B": "Blair"})

    text = (meeting / "transcript.md").read_text(encoding="utf-8")
    frontmatter = read_frontmatter(meeting / "transcript.md")
    assert frontmatter["participants"] == ["Alex", "Blair"]
    assert frontmatter["speaker_status"] == "confirmed"
    assert frontmatter["backup_status"] == "pending"
    assert "Metadata Phantom" not in frontmatter["speaker_aliases"]
    assert "**Alex** (0:00:01): One" in text
    assert "**Blair** (0:00:02): Two" in text


def test_confirmation_requires_every_actual_label_and_preserves_bytes(tmp_path: Path) -> None:
    meeting, _state = _reviewable_meeting(tmp_path)
    before = (meeting / "transcript.md").read_bytes()

    with pytest.raises(ValueError, match="Speaker B"):
        confirm_speaker_aliases(meeting, {"Speaker A": "Alex"})

    assert (meeting / "transcript.md").read_bytes() == before


def test_v2_review_can_keep_detected_labels_without_aliases(tmp_path: Path) -> None:
    meeting, _state = _reviewable_meeting(tmp_path)

    confirm_speaker_aliases(meeting, {}, keep_labels=True)

    text = (meeting / "transcript.md").read_text(encoding="utf-8")
    frontmatter = read_frontmatter(meeting / "transcript.md")
    assert frontmatter["speaker_aliases"] == {}
    assert frontmatter["speaker_status"] == "confirmed"
    assert frontmatter["participants"] == ["Speaker A", "Speaker B"]
    assert "**Speaker A** (0:00:01): One" in text
    assert "**Speaker B** (0:00:02): Two" in text


def test_confirmed_relabel_is_idempotent_but_alias_change_is_rejected(tmp_path: Path) -> None:
    meeting, _state = _reviewable_meeting(tmp_path)
    aliases = {"Speaker A": "Alex", "Speaker B": "Blair"}
    confirm_speaker_aliases(meeting, aliases)
    before = (meeting / "transcript.md").read_bytes()

    confirm_speaker_aliases(meeting, aliases)
    assert (meeting / "transcript.md").read_bytes() == before

    with pytest.raises(MeetingStateConflict, match="terminal"):
        confirm_speaker_aliases(meeting, {**aliases, "Speaker A": "Changed"})
    assert (meeting / "transcript.md").read_bytes() == before


def test_not_available_transcript_cannot_be_confirmed(tmp_path: Path) -> None:
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"audio")
    meeting = MeetingStore(tmp_path / "meetings").commit(
        audio,
        MeetingMeta("2026-08-10_11-00_empty", datetime(2026, 8, 10, tzinfo=UTC)),
    ).directory

    with pytest.raises(MeetingStateConflict, match="needs_review"):
        MeetingStateStore(meeting.parent).confirm_speakers(meeting, {})


def test_concurrent_backup_update_is_not_lost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    meeting, state = _reviewable_meeting(tmp_path)
    write_entered = threading.Event()
    release_write = threading.Event()
    backup_started = threading.Event()
    from meeting_memory.service import speaker_state

    original = speaker_state.MeetingDocument.replace_transcript
    state.transition_job(
        meeting,
        MeetingJob.BACKUP,
        MeetingJobState.NOT_REQUESTED,
        MeetingJobState.PENDING,
    )

    def blocked_write(document, text):
        write_entered.set()
        assert release_write.wait(timeout=2)
        return original(document, text)

    monkeypatch.setattr(speaker_state.MeetingDocument, "replace_transcript", blocked_write)
    confirm_thread = threading.Thread(
        target=confirm_speaker_aliases,
        args=(meeting, {"Speaker A": "Alex", "Speaker B": "Blair"}),
    )

    def update_backup() -> None:
        backup_started.set()
        state.transition_job(
            meeting,
            MeetingJob.BACKUP,
            MeetingJobState.PENDING,
            MeetingJobState.RUNNING,
        )

    confirm_thread.start()
    assert write_entered.wait(timeout=2)
    backup_thread = threading.Thread(target=update_backup)
    backup_thread.start()
    assert backup_started.wait(timeout=2)
    release_write.set()
    confirm_thread.join(timeout=2)
    backup_thread.join(timeout=2)

    frontmatter = read_frontmatter(meeting / "transcript.md")
    assert frontmatter["speaker_status"] == "confirmed"
    assert frontmatter["backup_status"] == "running"


def _reviewable_meeting(
    tmp_path: Path,
    *,
    complete_backup: bool = False,
    metadata_participants: tuple[str, ...] = (),
) -> tuple[Path, MeetingStateStore]:
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"audio")
    meta = MeetingMeta(
        "2026-08-10_10-30_review",
        datetime(2026, 8, 10, 10, 30, tzinfo=UTC),
        "Review",
        3,
    )
    meeting = MeetingStore(tmp_path / "meetings").commit(
        audio,
        meta,
        PostCommitPolicy(transcription=True, backup=complete_backup),
    ).directory
    state = MeetingStateStore(meeting.parent)
    state.transition_job(
        meeting,
        MeetingJob.TRANSCRIPTION,
        MeetingJobState.PENDING,
        MeetingJobState.RUNNING,
    )
    TranscriptStateStore(meeting.parent).succeed(
        meeting,
        meta,
        TranscriptResult(
            "tx-review",
            (
                TranscriptSegment("Speaker A", 1, "One"),
                TranscriptSegment("Speaker B", 2, "Two"),
            ),
        ),
    )
    if metadata_participants:
        state.merge_fields(
            meeting,
            ArtifactFieldOwner.TRANSCRIPTION,
            {"participants": list(metadata_participants)},
        )
    if complete_backup:
        state.transition_job(
            meeting, MeetingJob.BACKUP, MeetingJobState.PENDING, MeetingJobState.RUNNING
        )
        revision = compute_backup_revision(meeting / "recording.m4a", meeting / "transcript.md")
        prefix = f"meetings/{meeting.name}"
        state.complete_backup(
            meeting,
            revision,
            f"{prefix}/recording.m4a",
            f"{prefix}/transcript.md",
        )
    return meeting, state

"""Atomic schema-v2 Transcription completion tests."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

from meeting_memory.service.atomic_io import AtomicReplaceDurabilityUncertain
from meeting_memory.service.backup_revision import compute_backup_revision
from meeting_memory.service.meeting_document import MeetingDocumentDurabilityUncertain
from meeting_memory.service.meeting_state import MeetingStateConflict, MeetingStateStore
from meeting_memory.service.meeting_store import MeetingStore
from meeting_memory.service.storage import read_frontmatter
from meeting_memory.service.transcript_state import TranscriptStateStore
from meeting_memory.types.artifacts import MeetingJob
from meeting_memory.types.capabilities import MeetingJobState
from meeting_memory.types.meeting import MeetingMeta, PostCommitPolicy
from meeting_memory.types.transcript import TranscriptResult, TranscriptSegment


def test_success_replaces_body_and_state_once_and_reconciles_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    meeting, meta, state = _running_transcription(tmp_path, complete_backup=True)
    calls = 0
    from meeting_memory.service import meeting_document

    original = meeting_document.atomic_replace_text_at

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(meeting_document, "atomic_replace_text_at", counted)
    TranscriptStateStore(meeting.parent).succeed(meeting, meta, _transcript("tx-1"))

    frontmatter = read_frontmatter(meeting / "transcript.md")
    assert calls == 1
    assert frontmatter["transcription_status"] == "succeeded"
    assert frontmatter["assemblyai_id"] == "tx-1"
    assert frontmatter["speaker_status"] == "needs_review"
    assert frontmatter["backup_status"] == "pending"
    assert "**Speaker A** (0:00:05): Hello." in (meeting / "transcript.md").read_text()


def test_failure_preserves_existing_remote_id_and_sanitizes_provider_error(
    tmp_path: Path,
) -> None:
    meeting, _meta, _state = _running_transcription(tmp_path, provider_id="tx-existing")

    TranscriptStateStore(meeting.parent).fail(meeting)

    text = (meeting / "transcript.md").read_text(encoding="utf-8")
    frontmatter = read_frontmatter(meeting / "transcript.md")
    assert frontmatter["assemblyai_id"] == "tx-existing"
    assert frontmatter["transcription_status"] == "failed"
    assert "Retry Failed Transcriptions" in text
    assert "provider-secret-detail" not in text


def test_failure_normalizes_legacy_failure_sentinel_to_null(tmp_path: Path) -> None:
    meeting, _meta, state = _running_transcription(tmp_path)
    state.merge_fields(
        meeting,
        MeetingJob.TRANSCRIPTION,
        {"assemblyai_id": "transcription-failed"},
    )

    TranscriptStateStore(meeting.parent).fail(meeting)

    assert read_frontmatter(meeting / "transcript.md")["assemblyai_id"] is None


def test_success_compares_canonical_calendar_title(tmp_path: Path) -> None:
    meeting, meta, _state = _running_transcription(
        tmp_path,
        title="  Atomic\n\tTitle\x00  ",
    )

    TranscriptStateStore(meeting.parent).succeed(meeting, meta, _transcript("tx-1"))

    assert read_frontmatter(meeting / "transcript.md")["transcription_status"] == "succeeded"


def test_provider_id_and_meta_conflicts_leave_bytes_unchanged(tmp_path: Path) -> None:
    meeting, meta, _state = _running_transcription(tmp_path, provider_id="tx-a")
    before = (meeting / "transcript.md").read_bytes()
    store = TranscriptStateStore(meeting.parent)

    with pytest.raises(MeetingStateConflict, match="not tx-b"):
        store.succeed(meeting, meta, _transcript("tx-b"))
    with pytest.raises(MeetingStateConflict, match="calendar_title"):
        store.succeed(meeting, meta.with_title("Changed"), _transcript("tx-a"))
    with pytest.raises(MeetingStateConflict, match="not tx-b"):
        store.fail(meeting, "tx-b")

    assert (meeting / "transcript.md").read_bytes() == before


def test_two_competing_finishers_only_one_wins(tmp_path: Path) -> None:
    meeting, meta, _state = _running_transcription(tmp_path)
    barrier = threading.Barrier(2)
    completed: list[str] = []
    conflicts: list[Exception] = []

    def finish(identifier: str) -> None:
        barrier.wait()
        try:
            TranscriptStateStore(meeting.parent).succeed(
                meeting, meta, _transcript(identifier)
            )
            completed.append(identifier)
        except MeetingStateConflict as exc:
            conflicts.append(exc)

    threads = [threading.Thread(target=finish, args=(identifier,)) for identifier in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert len(completed) == len(conflicts) == 1
    assert read_frontmatter(meeting / "transcript.md")["assemblyai_id"] == completed[0]


def test_post_rename_fsync_failure_reports_applied_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    meeting, meta, _state = _running_transcription(tmp_path)
    from meeting_memory.service import meeting_document

    original = meeting_document.atomic_replace_text_at

    def uncertain(*args, **kwargs):
        original(*args, **kwargs)
        raise AtomicReplaceDurabilityUncertain("transcript.md", OSError("fsync"))

    monkeypatch.setattr(meeting_document, "atomic_replace_text_at", uncertain)
    with pytest.raises(MeetingDocumentDurabilityUncertain) as captured:
        TranscriptStateStore(meeting.parent).succeed(meeting, meta, _transcript("tx-1"))

    assert captured.value.frontmatter["transcription_status"] == "succeeded"
    assert read_frontmatter(meeting / "transcript.md")["transcription_status"] == "succeeded"


def test_pinned_write_does_not_follow_swapped_meeting_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    meeting, meta, _state = _running_transcription(tmp_path)
    external = tmp_path / "external"
    external.mkdir()
    (external / "transcript.md").write_text("outside", encoding="utf-8")
    moved = meeting.with_name(f"{meeting.name}-moved")
    from meeting_memory.service import transcript_state

    original = transcript_state.MeetingDocument.replace_transcript

    def swap_then_write(document, text):
        meeting.rename(moved)
        meeting.symlink_to(external, target_is_directory=True)
        return original(document, text)

    monkeypatch.setattr(transcript_state.MeetingDocument, "replace_transcript", swap_then_write)
    TranscriptStateStore(meeting.parent).succeed(meeting, meta, _transcript("tx-1"))

    assert (external / "transcript.md").read_text(encoding="utf-8") == "outside"
    assert read_frontmatter(moved / "transcript.md")["transcription_status"] == "succeeded"


def _running_transcription(
    tmp_path: Path,
    *,
    provider_id: str | None = None,
    complete_backup: bool = False,
    title: str = "Atomic",
) -> tuple[Path, MeetingMeta, MeetingStateStore]:
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"audio")
    meta = MeetingMeta(
        "2026-08-10_10-00_atomic",
        datetime(2026, 8, 10, 10, 0, tzinfo=UTC),
        title,
        2,
    )
    meeting = MeetingStore(tmp_path / "meetings").commit(
        audio,
        meta,
        PostCommitPolicy(transcription=True, backup=complete_backup),
    ).directory
    state = MeetingStateStore(meeting.parent)
    updates = {"assemblyai_id": provider_id} if provider_id else None
    state.transition_job(
        meeting,
        MeetingJob.TRANSCRIPTION,
        MeetingJobState.PENDING,
        MeetingJobState.RUNNING,
        updates,
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
    return meeting, meta, state


def _transcript(identifier: str) -> TranscriptResult:
    return TranscriptResult(
        identifier,
        (TranscriptSegment("Speaker A", 5, "Hello."),),
    )

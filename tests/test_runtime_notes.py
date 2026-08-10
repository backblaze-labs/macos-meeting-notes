from datetime import UTC, datetime
from pathlib import Path

import pytest

from meeting_memory.service import legacy_snapshot
from meeting_memory.service.meeting_state import MeetingStateStore
from meeting_memory.service.meeting_store import MeetingStore
from meeting_memory.service.runtime_notes import generate_owned_notes, generate_v2_notes
from meeting_memory.service.storage import write_meeting_dir
from meeting_memory.service.transcript_review import confirm_speaker_aliases
from meeting_memory.service.transcript_state import TranscriptStateStore
from meeting_memory.types.artifacts import ArtifactFieldOwner, MeetingJob
from meeting_memory.types.capabilities import MeetingJobState
from meeting_memory.types.meeting import MeetingMeta, PostCommitPolicy
from meeting_memory.types.summary import SummaryResult
from meeting_memory.types.transcript import TranscriptResult, TranscriptSegment


class Summarizer:
    def __init__(self, callback=None) -> None:
        self.callback = callback

    def summarize(self, _text: str) -> SummaryResult:
        if self.callback:
            self.callback()
        return SummaryResult(summary="Reviewed")


def _confirmed_meeting(tmp_path: Path):
    meetings = tmp_path / "meetings"
    audio = tmp_path / "source.m4a"
    audio.write_bytes(b"audio")
    meta = MeetingMeta(
        "2026-08-10_10-00_sync",
        datetime(2026, 8, 10, 10, tzinfo=UTC),
        "Sync",
    )
    files = MeetingStore(meetings).commit(
        audio,
        meta,
        PostCommitPolicy(transcription=True),
    )
    state = MeetingStateStore(meetings)
    state.transition_job(
        files.directory,
        MeetingJob.TRANSCRIPTION,
        MeetingJobState.PENDING,
        MeetingJobState.RUNNING,
    )
    TranscriptStateStore(meetings).succeed(
        files.directory,
        meta,
        TranscriptResult("job-1", (TranscriptSegment("A", 0, "Hello"),)),
    )
    state.confirm_speakers(files.directory, {"A": "Alex"}, expected_status="needs_review")
    return meetings, files, state


def test_v2_notes_rejects_symlink_without_touching_target(tmp_path: Path) -> None:
    meetings, files, _state = _confirmed_meeting(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    files.notes_path.symlink_to(outside)

    with pytest.raises(ValueError, match="regular file"):
        generate_v2_notes(meetings, files.directory, Summarizer())

    assert outside.read_text(encoding="utf-8") == "secret"
    assert files.notes_path.is_symlink()


def test_v2_notes_rejects_transcript_change_during_remote_call(tmp_path: Path) -> None:
    meetings, files, state = _confirmed_meeting(tmp_path)
    summarizer = Summarizer(
        lambda: state.merge_fields(
            files.directory,
            ArtifactFieldOwner.SPEAKERS,
            {"speaker_candidates": ["Alex"]},
        )
    )

    with pytest.raises(ValueError, match="changed"):
        generate_v2_notes(meetings, files.directory, summarizer)

    assert not files.notes_path.exists()


def test_v2_notes_publishes_after_stable_confirmed_snapshot(tmp_path: Path) -> None:
    meetings, files, _state = _confirmed_meeting(tmp_path)

    notes = generate_v2_notes(meetings, files.directory, Summarizer())

    assert notes.read_text(encoding="utf-8").startswith("---\n")
    assert "Reviewed" in notes.read_text(encoding="utf-8")


def test_owned_notes_preserves_legacy_meeting_compatibility(tmp_path: Path) -> None:
    source = tmp_path / "legacy.m4a"
    source.write_bytes(b"audio")
    files = write_meeting_dir(
        tmp_path / "meetings",
        MeetingMeta("legacy", datetime(2026, 8, 10, 9, tzinfo=UTC), "Legacy"),
        source,
        TranscriptResult("job-old", (TranscriptSegment("A", 0, "Hello"),)),
        SummaryResult.skipped(),
    )
    confirm_speaker_aliases(files.directory, {"A": "Alex"})

    notes = generate_owned_notes(tmp_path / "meetings", files.directory, Summarizer())

    rendered = notes.read_text(encoding="utf-8")
    assert "Reviewed" in rendered
    assert "**Source:** transcript.md" in rendered


def test_legacy_notes_rejects_symlink_without_touching_target(tmp_path: Path) -> None:
    source = tmp_path / "legacy.m4a"
    source.write_bytes(b"audio")
    files = write_meeting_dir(
        tmp_path / "meetings",
        MeetingMeta("legacy", datetime(2026, 8, 10, 9, tzinfo=UTC), "Legacy"),
        source,
        TranscriptResult("job-old", (TranscriptSegment("A", 0, "Hello"),)),
        SummaryResult.skipped(),
    )
    confirm_speaker_aliases(files.directory, {"A": "Alex"})
    outside = tmp_path / "outside.txt"
    outside.write_text("private", encoding="utf-8")
    files.notes_path.unlink()
    files.notes_path.symlink_to(outside)

    with pytest.raises(ValueError, match="regular file"):
        generate_owned_notes(tmp_path / "meetings", files.directory, Summarizer())

    assert outside.read_text(encoding="utf-8") == "private"


def test_legacy_notes_rejects_transcript_change_during_remote_call(
    tmp_path: Path,
) -> None:
    source = tmp_path / "legacy.m4a"
    source.write_bytes(b"audio")
    files = write_meeting_dir(
        tmp_path / "meetings",
        MeetingMeta("legacy", datetime(2026, 8, 10, 9, tzinfo=UTC), "Legacy"),
        source,
        TranscriptResult("job-old", (TranscriptSegment("A", 0, "Hello"),)),
        SummaryResult.skipped(),
    )
    confirm_speaker_aliases(files.directory, {"A": "Alex"})
    files.notes_path.unlink()

    def mutate_transcript() -> None:
        text = files.transcript_path.read_text(encoding="utf-8")
        files.transcript_path.write_text(f"{text}\nchanged\n", encoding="utf-8")

    with pytest.raises(ValueError, match="changed"):
        generate_owned_notes(
            tmp_path / "meetings",
            files.directory,
            Summarizer(mutate_transcript),
        )

    assert not files.notes_path.exists()


def test_legacy_notes_rejects_visible_metadata_swap_after_compare(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "legacy.m4a"
    source.write_bytes(b"audio")
    files = write_meeting_dir(
        tmp_path / "meetings",
        MeetingMeta("legacy", datetime(2026, 8, 10, 9, tzinfo=UTC), "Legacy"),
        source,
        TranscriptResult("job-old", (TranscriptSegment("A", 0, "Hello"),)),
        SummaryResult.skipped(),
    )
    confirm_speaker_aliases(files.directory, {"A": "Alex"})
    files.notes_path.unlink()
    original_read = legacy_snapshot._read_text
    swapped = False

    def swap_after_read(descriptor: int) -> str:
        nonlocal swapped
        text = original_read(descriptor)
        if not swapped:
            swapped = True
            files.transcript_path.rename(files.transcript_path.with_suffix(".original"))
            files.transcript_path.write_text(f"{text}\nchanged\n", encoding="utf-8")
        return text

    monkeypatch.setattr(legacy_snapshot, "_read_text", swap_after_read)

    with pytest.raises(ValueError, match="changed"):
        generate_owned_notes(tmp_path / "meetings", files.directory, Summarizer())

    assert not files.notes_path.exists()
    assert files.transcript_path.read_text(encoding="utf-8").endswith("changed\n")

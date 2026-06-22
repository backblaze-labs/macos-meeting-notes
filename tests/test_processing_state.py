"""Tests for resumable processing-state detection."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from meeting_memory.service.markdown import render_notes_markdown
from meeting_memory.service.processing_state import list_pending_processing_tasks
from meeting_memory.service.storage import read_frontmatter, write_meeting_dir
from meeting_memory.service.transcript_review import confirm_speaker_aliases
from meeting_memory.types.meeting import MeetingMeta
from meeting_memory.types.summary import SummaryResult
from meeting_memory.types.transcript import TranscriptResult, TranscriptSegment


def test_processing_tasks_include_speaker_review_and_missing_notes(tmp_path: Path) -> None:
    review = _write_meeting(tmp_path, "2026-06-22_10-00_review", "Review")
    confirmed = _write_meeting(tmp_path, "2026-06-22_11-00_notes", "Notes")
    confirm_speaker_aliases(confirmed.directory, {"Speaker A": "Alex"})

    tasks = list_pending_processing_tasks(tmp_path / "meetings")

    assert [(task.meeting.slug, task.action, task.label) for task in tasks] == [
        (confirmed.meta.slug, "generate_notes", "Generate notes"),
        (review.meta.slug, "review_speakers", "Review speakers"),
    ]


def test_processing_tasks_retry_failed_or_skipped_notes(tmp_path: Path) -> None:
    failed = _write_meeting(tmp_path, "2026-06-22_12-00_failed", "Failed")
    skipped = _write_meeting(tmp_path, "2026-06-22_13-00_skipped", "Skipped")
    done = _write_meeting(tmp_path, "2026-06-22_14-00_done", "Done")
    for files in (failed, skipped, done):
        confirm_speaker_aliases(files.directory, {"Speaker A": "Alex"})
    _write_notes(failed.directory, SummaryResult.failed())
    _write_notes(skipped.directory, SummaryResult.skipped())
    _write_notes(done.directory, SummaryResult(summary="Done."))

    tasks = list_pending_processing_tasks(tmp_path / "meetings")

    assert [(task.meeting.slug, task.status, task.label) for task in tasks] == [
        (skipped.meta.slug, "skipped", "Retry notes"),
        (failed.meta.slug, "failed", "Retry notes"),
    ]


def _write_meeting(tmp_path: Path, slug: str, title: str):
    audio = tmp_path / f"{slug}.m4a"
    audio.write_bytes(b"audio")
    files = write_meeting_dir(
        tmp_path / "meetings",
        MeetingMeta(
            slug=slug,
            started_at=datetime(2026, 6, 22, int(slug[11:13]), int(slug[14:16]), tzinfo=UTC),
            calendar_title=title,
            duration_minutes=20,
        ),
        audio,
        TranscriptResult(
            assemblyai_id=f"tx-{slug}",
            segments=(TranscriptSegment("Speaker A", 5, "Hello."),),
        ),
        SummaryResult.skipped(),
    )
    if files.notes_path and files.notes_path.exists():
        files.notes_path.unlink()
    return files


def _write_notes(meeting_dir: Path, summary: SummaryResult) -> None:
    transcript_path = meeting_dir / "transcript.md"
    frontmatter = read_frontmatter(transcript_path)
    notes = render_notes_markdown(
        MeetingMeta(
            slug=str(frontmatter["id"]),
            started_at=datetime.fromisoformat(str(frontmatter["date"])),
            calendar_title=str(frontmatter["calendar_title"]),
            duration_minutes=int(frontmatter["duration_minutes"]),
        ),
        summary,
    )
    notes_path = meeting_dir / "notes.md"
    notes_path.write_text(notes, encoding="utf-8")

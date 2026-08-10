"""Detect resumable post-processing work from local meeting artifacts."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from meeting_memory.service.ownership import inspect_meeting_snapshot
from meeting_memory.service.storage import NOTES_MARKDOWN, read_frontmatter
from meeting_memory.service.transcript_review import SPEAKER_LABEL_RE
from meeting_memory.types.meeting import RecentMeeting
from meeting_memory.types.processing import ProcessingStatus, ProcessingTask

RETRYABLE_NOTE_STATUSES = {"failed", "skipped"}


def list_pending_processing_tasks(meetings_dir: Path, limit: int = 5) -> list[ProcessingTask]:
    if not meetings_dir.exists():
        return []

    tasks = [
        task
        for meeting_dir in meetings_dir.iterdir()
        if meeting_dir.is_dir()
        for task in [_task_for_meeting(meeting_dir)]
        if task is not None
    ]
    return sorted(tasks, key=lambda item: item.meeting.started_at, reverse=True)[:limit]


def _task_for_meeting(meeting_dir: Path) -> ProcessingTask | None:
    try:
        snapshot = inspect_meeting_snapshot(meeting_dir)
        if snapshot is None:
            return None
        frontmatter = snapshot.frontmatter
        transcript_path = snapshot.artifact.transcript_path
        meeting = _recent_from_frontmatter(meeting_dir, transcript_path, frontmatter)
    except (KeyError, OSError, TypeError, UnicodeError, ValueError):
        return None

    if str(frontmatter.get("speaker_status") or "needs_review") != "confirmed":
        if not SPEAKER_LABEL_RE.search(snapshot.body):
            return None
        return ProcessingTask(
            meeting=meeting,
            stage="speaker_review",
            action="review_speakers",
            status="waiting",
            label="Review speakers",
        )

    notes_path = meeting_dir / NOTES_MARKDOWN
    if not notes_path.exists():
        return _notes_task(meeting, "waiting", "Generate notes")

    status = _notes_status(notes_path)
    if status in RETRYABLE_NOTE_STATUSES:
        return _notes_task(meeting, status, "Retry notes")
    return None


def _notes_task(meeting: RecentMeeting, status: ProcessingStatus, label: str) -> ProcessingTask:
    return ProcessingTask(
        meeting=meeting,
        stage="notes",
        action="generate_notes",
        status=status,
        label=label,
    )


def _notes_status(notes_path: Path) -> str:
    try:
        frontmatter = read_frontmatter(notes_path)
    except (OSError, ValueError):
        return "failed"
    return str(frontmatter.get("summary_status") or "")


def _recent_from_frontmatter(
    meeting_dir: Path,
    markdown_path: Path,
    frontmatter: dict[str, object],
) -> RecentMeeting:
    return RecentMeeting(
        slug=str(frontmatter["id"]),
        calendar_title=str(frontmatter["calendar_title"]),
        started_at=datetime.fromisoformat(str(frontmatter["date"])),
        directory=meeting_dir,
        markdown_path=markdown_path,
    )

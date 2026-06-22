"""Retry failed local processing using meeting frontmatter as durable state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from meeting_memory.service.storage import (
    MEETING_MARKDOWN,
    NOTES_MARKDOWN,
    RECORDING_AUDIO,
    is_ours,
    read_frontmatter,
)
from meeting_memory.types.meeting import MeetingFiles, MeetingMeta


class MeetingProcessor(Protocol):
    def process_files(self, files: MeetingFiles):
        """Re-run processing for an existing meeting directory."""


@dataclass(frozen=True)
class ProcessingRetryResult:
    attempted: int = 0
    completed: int = 0
    failed: int = 0


def retry_failed_processing(
    meetings_dir: Path,
    processor: MeetingProcessor,
) -> ProcessingRetryResult:
    if not meetings_dir.exists():
        return ProcessingRetryResult()

    attempted = completed = failed = 0
    for meeting_dir in sorted(path for path in meetings_dir.iterdir() if path.is_dir()):
        if not is_ours(meeting_dir):
            continue
        frontmatter = read_frontmatter(meeting_dir / MEETING_MARKDOWN)
        if not should_retry_processing(frontmatter):
            continue

        attempted += 1
        try:
            processor.process_files(_files_from_frontmatter(meeting_dir, frontmatter))
        except Exception:
            failed += 1
            continue
        completed += 1
    return ProcessingRetryResult(attempted=attempted, completed=completed, failed=failed)


def should_retry_processing(frontmatter: dict[str, object]) -> bool:
    return frontmatter.get("assemblyai_id") == "transcription-failed"


def _files_from_frontmatter(meeting_dir: Path, frontmatter: dict[str, object]) -> MeetingFiles:
    meta = MeetingMeta(
        slug=str(frontmatter["id"]),
        started_at=datetime.fromisoformat(str(frontmatter["date"])),
        calendar_title=str(frontmatter["calendar_title"]),
        duration_minutes=int(frontmatter["duration_minutes"]),
    )
    return MeetingFiles(
        meta=meta,
        directory=meeting_dir,
        audio_path=meeting_dir / RECORDING_AUDIO,
        markdown_path=meeting_dir / MEETING_MARKDOWN,
        notes_path=meeting_dir / NOTES_MARKDOWN,
    )

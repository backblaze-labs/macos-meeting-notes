"""Tray callbacks for resumable processing tasks."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from meeting_memory.types.processing import ProcessingTask


def run_processing_task(
    task: ProcessingTask,
    *,
    review_speakers: Callable[[Path], None],
    generate_notes: Callable[[Path], None],
) -> None:
    if task.action == "review_speakers":
        review_speakers(task.meeting.directory)
    elif task.action == "generate_notes":
        generate_notes(task.meeting.directory)

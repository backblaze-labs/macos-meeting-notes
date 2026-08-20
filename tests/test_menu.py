"""Tests for tray menu helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from meeting_memory.types.meeting import RecentMeeting
from meeting_memory.types.processing import ProcessingTask
from meeting_memory.ui.menu import (
    NO_MEETINGS_LABEL,
    processing_header_label,
    processing_task_label,
    processing_task_tooltip,
    recent_meeting_labels,
    recording_label,
    review_speakers_label,
    tray_title,
)


def test_recording_labels() -> None:
    assert recording_label(is_recording=False) == "▶ Start Recording"
    assert recording_label(is_recording=True, duration_seconds=65) == "■ Stop Recording · 01:05"
    assert (
        recording_label(is_recording=True, duration_seconds=3661) == "■ Stop Recording · 01:01:01"
    )
    assert tray_title(is_recording=False) is None
    assert tray_title(is_recording=True, duration_seconds=65) == "01:05"
    assert recording_label(is_recording=True, audio_warning=True).startswith("⚠︎ ")
    assert tray_title(is_recording=True, audio_warning=True) == "⚠︎ 00:00"


def test_recent_meeting_labels() -> None:
    meetings = [
            RecentMeeting(
                slug=f"slug-{index}",
                calendar_title=f"Product Sync {index}",
                started_at=datetime(2026, 6, 11, 9, index, tzinfo=UTC),
                directory=Path(f"/tmp/meeting-{index}"),
                markdown_path=Path(f"/tmp/meeting-{index}/meeting.md"),
            )
            for index in range(4)
        ]
    labels = recent_meeting_labels(meetings)

    assert labels == [
        "2026-06-11 09:00 · Product Sync 0",
        "2026-06-11 09:01 · Product Sync 1",
        "2026-06-11 09:02 · Product Sync 2",
    ]
    assert recent_meeting_labels([]) == [NO_MEETINGS_LABEL]


def test_review_speakers_label() -> None:
    meeting = RecentMeeting(
        slug="slug",
        calendar_title="Product Sync",
        started_at=datetime(2026, 6, 11, 9, 0, tzinfo=UTC),
        directory=Path("/tmp/meeting"),
        markdown_path=Path("/tmp/meeting/transcript.md"),
    )

    assert review_speakers_label(meeting) == "2026-06-11 09:00 · Review speakers · Product Sync"


def test_processing_task_label() -> None:
    meeting = RecentMeeting(
        slug="slug",
        calendar_title="Product Sync",
        started_at=datetime(2026, 6, 11, 9, 0, tzinfo=UTC),
        directory=Path("/tmp/meeting"),
        markdown_path=Path("/tmp/meeting/transcript.md"),
    )

    task = ProcessingTask(
        meeting=meeting,
        stage="notes",
        action="generate_notes",
        status="waiting",
        label="Generate notes",
    )

    assert processing_header_label(1) == "Pending Meeting Tasks (1)"
    assert processing_task_label(task) == "2026-06-11 09:00 · Generate notes · Product Sync"
    assert processing_task_tooltip(task) == "Generate notes from the reviewed transcript."

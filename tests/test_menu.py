"""Tests for tray menu helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from meeting_memory.types.meeting import RecentMeeting
from meeting_memory.ui.menu import NO_MEETINGS_LABEL, recent_meeting_labels, recording_label


def test_recording_labels() -> None:
    assert recording_label(is_recording=False) == "▶ Start Recording"
    assert recording_label(is_recording=True, duration_seconds=65) == "■ Stop Recording · 01:05"
    assert (
        recording_label(is_recording=True, duration_seconds=3661)
        == "■ Stop Recording · 01:01:01"
    )


def test_recent_meeting_labels() -> None:
    labels = recent_meeting_labels(
        [
            RecentMeeting(
                slug="slug",
                calendar_title="Product Sync",
                started_at=datetime(2026, 6, 11, 9, 0, tzinfo=UTC),
                directory=Path("/tmp/meeting"),
                markdown_path=Path("/tmp/meeting/meeting.md"),
            )
        ]
    )

    assert labels == ["2026-06-11 09:00 · Product Sync"]
    assert recent_meeting_labels([]) == [NO_MEETINGS_LABEL]

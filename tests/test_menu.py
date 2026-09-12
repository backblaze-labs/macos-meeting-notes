"""Tests for tray menu helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from meeting_memory.types.meeting import RecentMeeting
from meeting_memory.ui import menu
from meeting_memory.ui.menu import (
    NO_MEETINGS_LABEL,
    recent_meeting_labels,
    recording_label,
)


def test_recording_labels() -> None:
    assert recording_label(is_recording=False) == "▶ Start Recording"
    assert recording_label(is_recording=True, duration_seconds=65) == "■ Stop Recording · 01:05"
    assert (
        recording_label(is_recording=True, duration_seconds=3661) == "■ Stop Recording · 01:01:01"
    )
    assert recording_label(is_recording=True, audio_warning=True).startswith("⚠︎ ")


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


def test_tray_title_shows_a_dot_and_timer_only_while_recording() -> None:
    assert menu.tray_title(is_recording=False) is None
    assert menu.tray_title(is_recording=True, duration_seconds=65) == "\u25cf 01:05"
    assert menu.tray_title(is_recording=True, duration_seconds=3661) == "\u25cf 01:01:01"
    assert menu.tray_title(is_recording=True, duration_seconds=5, audio_warning=True) == (
        "\u26a0\ufe0e 00:05"
    )

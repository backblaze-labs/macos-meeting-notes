"""Tests for native recording mode selection."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from meeting_memory.service.audio_modes import (
    FULL_MEETING,
    SILENT_SYSTEM_ONLY,
    apply_audio_mode,
)


def test_full_meeting_captures_both_sources_and_monitors_audio() -> None:
    assert FULL_MEETING.capture_system_audio is True
    assert FULL_MEETING.capture_microphone is True
    assert FULL_MEETING.monitor_audio is True


def test_silent_mode_captures_system_without_microphone_or_monitoring() -> None:
    assert SILENT_SYSTEM_ONLY.capture_system_audio is True
    assert SILENT_SYSTEM_ONLY.capture_microphone is False
    assert SILENT_SYSTEM_ONLY.monitor_audio is False


def test_apply_audio_mode_updates_next_native_capture() -> None:
    recorder = FakeRecorder(capture_mode="full-meeting")

    apply_audio_mode(SILENT_SYSTEM_ONLY, recorder)

    assert recorder.capture_mode == "silent-system-only"


def test_apply_audio_mode_refuses_active_recording() -> None:
    recorder = FakeRecorder(capture_mode="full-meeting", is_recording=True)

    with pytest.raises(RuntimeError, match="Stop the current recording"):
        apply_audio_mode(SILENT_SYSTEM_ONLY, recorder)


@dataclass
class FakeRecorder:
    capture_mode: str
    is_recording: bool = False

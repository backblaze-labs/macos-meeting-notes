"""Tests for propagating asynchronous recording failures to the tray."""

from __future__ import annotations

import queue
import threading
import time

from meeting_memory.types.audio import (
    CaptureDiagnostics,
    CaptureHealthWarning,
    CaptureSourceDiagnostics,
)
from meeting_memory.types.events import NotifyEvent
from meeting_memory.ui.recording_health import (
    RecordingHealthMonitor,
    completed_capture_warning,
)


def test_recording_health_poll_is_non_blocking_and_single_flight() -> None:
    events: queue.Queue[object] = queue.Queue()
    recorder = BlockingFailingRecorder()
    monitor = RecordingHealthMonitor(recorder, events)

    started_at = time.monotonic()
    monitor.poll()
    elapsed = time.monotonic() - started_at
    assert elapsed < 0.3
    assert recorder.entered.wait(timeout=1)

    monitor.poll()
    assert recorder.calls == 1

    recorder.release.set()

    assert events.get(timeout=1) == NotifyEvent(
        "Recording stopped unexpectedly",
        "Screen & System Audio permission was revoked",
    )


def test_recording_health_warns_while_recording_is_still_active() -> None:
    events: queue.Queue[object] = queue.Queue()
    recorder = WarningRecorder()

    RecordingHealthMonitor(recorder, events).poll()

    assert events.get(timeout=1) == NotifyEvent(
        title="Recording audio needs attention",
        body="No Zoom/system audio is reaching this recording.",
        action_label="Stop",
        action="stop_recording",
    )


def test_completed_recording_repeats_any_capture_warning() -> None:
    sources = (
        CaptureSourceDiagnostics("system", 0, 0, 0),
        CaptureSourceDiagnostics("microphone", 1, 1_600, 0.2),
    )
    diagnostics = CaptureDiagnostics(
        "full-meeting",
        "Built-in",
        20,
        sources,
        warnings=("system_missing",),
    )

    assert completed_capture_warning(diagnostics) == NotifyEvent(
        "Recording completed with an audio warning",
        "Audio was saved, but diagnostics found: system missing. "
        "Review this meeting before relying on its transcript.",
    )


class BlockingFailingRecorder:
    def __init__(self) -> None:
        self.is_recording = True
        self.calls = 0
        self.entered = threading.Event()
        self.release = threading.Event()

    def check_health(self) -> None:
        self.calls += 1
        self.entered.set()
        if not self.release.wait(timeout=1):
            raise TimeoutError("test did not release health check")
        raise RuntimeError("Screen & System Audio permission was revoked")


class WarningRecorder:
    is_recording = True

    def check_health(self) -> CaptureHealthWarning:
        return CaptureHealthWarning(
            "system_missing",
            "No Zoom/system audio is reaching this recording.",
        )

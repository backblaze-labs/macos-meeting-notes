"""Tests for propagating asynchronous recording failures to the tray."""

from __future__ import annotations

import queue
import threading
import time

from meeting_memory.types.events import NotifyEvent
from meeting_memory.ui.recording_health import RecordingHealthMonitor


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

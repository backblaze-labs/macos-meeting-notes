"""Tests for durable post-recording worker launch."""

from __future__ import annotations

import queue
from datetime import UTC, datetime
from pathlib import Path

import pytest

from meeting_memory.service.recovery import find_recovered_recordings
from meeting_memory.types.events import NotifyEvent
from meeting_memory.types.meeting import MeetingMeta
from meeting_memory.ui.processing_launch import launch_processing


@pytest.mark.parametrize("failure_stage", ["construct", "start"])
def test_launch_failure_marks_audio_for_recovery(
    tmp_path: Path,
    failure_stage: str,
) -> None:
    audio_path = tmp_path / "meeting-memory-2026-06-11_09-00_product-sync.m4a"
    audio_path.write_bytes(b"audio")
    meta = MeetingMeta(
        "2026-06-11_09-00_product-sync",
        datetime(2026, 6, 11, 9, 0, tzinfo=UTC),
        "Product Sync",
    )
    events: queue.Queue[object] = queue.Queue()
    calls = []

    launched = launch_processing(
        thread_factory=FailingThreadFactory(failure_stage),
        event_sink=events.put,
        callback=lambda audio, meeting: calls.append((audio, meeting)),
        audio_path=audio_path,
        meta=meta,
    )

    assert launched is False
    assert calls == []
    assert events.get_nowait() == NotifyEvent(
        "Recording saved",
        "Product Sync · processing queued",
        show_notification=False,
    )
    failure = events.get_nowait()
    assert isinstance(failure, NotifyEvent)
    assert failure.title == "Processing could not start"
    assert failure.body.endswith("Retry from Debugging.")
    recovered = find_recovered_recordings(tmp_path)
    assert len(recovered) == 1
    assert recovered[0].audio_path == audio_path
    assert recovered[0].meta == meta


class FailingThread:
    def start(self) -> None:
        raise RuntimeError("thread start failed")


class FailingThreadFactory:
    def __init__(self, failure_stage: str) -> None:
        self.failure_stage = failure_stage

    def __call__(self, **_kwargs):
        if self.failure_stage == "construct":
            raise RuntimeError("thread construct failed")
        return FailingThread()

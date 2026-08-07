"""Tests for recovery-marker lifetime across pipeline processing."""

from __future__ import annotations

import queue
from datetime import UTC, datetime
from pathlib import Path

from meeting_memory.service.recovery import (
    find_recovered_recordings,
    mark_audio_for_recovery,
)
from meeting_memory.types.meeting import MeetingMeta
from meeting_memory.ui.controller import TrayController


def test_pipeline_failure_keeps_converted_audio_recoverable(tmp_path: Path) -> None:
    audio_path = tmp_path / "meeting-memory-2026-06-11_09-00_product-sync.m4a"
    audio_path.write_bytes(b"audio")
    meta = MeetingMeta(
        "2026-06-11_09-00_product-sync",
        datetime(2026, 6, 11, 9, 0, tzinfo=UTC),
        "Product Sync",
    )
    marker = mark_audio_for_recovery(audio_path, meta)
    recording = find_recovered_recordings(tmp_path)[0]
    events: queue.Queue[object] = queue.Queue()
    controller = TrayController(
        settings=object(),
        recorder=object(),
        pipeline=FailingPipeline(),
        event_queue=events,
    )

    controller._process_recovered_recording(recording)

    assert marker.exists()
    assert find_recovered_recordings(tmp_path)[0].audio_path == audio_path
    assert [event.title for event in controller.drain_events()] == [
        "Recovered recording queued",
        "Meeting processing failed",
    ]


def test_pipeline_success_clears_recovery_marker(tmp_path: Path) -> None:
    audio_path = tmp_path / "meeting-memory-2026-06-11_09-00_done.m4a"
    audio_path.write_bytes(b"audio")
    meta = MeetingMeta(
        "2026-06-11_09-00_done",
        datetime(2026, 6, 11, 9, 0, tzinfo=UTC),
        "Done",
    )
    marker = mark_audio_for_recovery(audio_path, meta)
    controller = TrayController(
        settings=object(),
        recorder=object(),
        pipeline=SuccessfulPipeline(),
        event_queue=queue.Queue(),
    )

    controller._process_recovered_recording(find_recovered_recordings(tmp_path)[0])

    assert not marker.exists()
    assert find_recovered_recordings(tmp_path) == []


class FailingPipeline:
    def run(self, _audio_path: Path, _meta: MeetingMeta) -> None:
        raise OSError("meeting directory unavailable")


class SuccessfulPipeline:
    def run(self, _audio_path: Path, _meta: MeetingMeta) -> None:
        return None

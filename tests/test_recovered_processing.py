"""Recovery discovery stays indexed and local-first after runtime cutover."""

from __future__ import annotations

import queue
from datetime import UTC, datetime

from meeting_memory.service.recorder import RecorderService
from meeting_memory.service.recovery import mark_audio_for_recovery
from meeting_memory.service.recovery_index import (
    create_recovery_session,
    discover_indexed_recoveries,
)
from meeting_memory.types.meeting import MeetingMeta
from meeting_memory.ui.controller import TrayController


def test_normal_recovery_discovery_ignores_legacy_temp_markers(tmp_path) -> None:
    legacy_audio = tmp_path / "meeting-memory-2026-06-11_09-00_legacy.m4a"
    legacy_audio.write_bytes(b"legacy")
    meta = _meta("legacy")
    mark_audio_for_recovery(legacy_audio, meta)
    controller = TrayController(
        settings=object(),
        recorder=type("Recorder", (), {"temp_dir": tmp_path})(),
        event_queue=queue.Queue(),
    )

    assert controller.recovered_recordings() == []


def test_normal_recovery_discovery_returns_private_indexed_sessions(tmp_path) -> None:
    meta = _meta("indexed")
    entry = create_recovery_session(tmp_path, meta)
    entry.wav_path.write_bytes(b"indexed audio")
    controller = TrayController(
        settings=object(),
        recorder=type("Recorder", (), {"temp_dir": tmp_path})(),
        event_queue=queue.Queue(),
    )

    recovered = controller.recovered_recordings()

    assert len(recovered) == 1
    assert recovered[0].session_device == entry.session_device
    assert recovered[0].session_inode == entry.session_inode


def test_live_capture_is_hidden_and_rejected_as_recovery(tmp_path) -> None:
    staging = tmp_path / "recordings"

    def start_capture(_mode, path):
        path.write_bytes(b"RIFF\x00\x00\x00\x00WAVElive")
        return type("Capture", (), {"stop": lambda self: None})()

    recorder = RecorderService(temp_dir=staging, capture_starter=start_capture)
    session = recorder.start("Live")
    calls: list[object] = []
    committer = type(
        "Committer",
        (),
        {"commit": lambda self, entry, meta: calls.append((entry, meta))},
    )()
    controller = TrayController(
        settings=object(),
        recorder=recorder,
        committer=committer,
        event_queue=queue.Queue(),
    )
    exposed = discover_indexed_recoveries(staging)[0]

    assert session is not None
    assert controller.recovered_recordings() == []
    assert controller.run_local_commit(exposed, exposed.meta) is False
    controller.process_recovered_recording(exposed)
    assert calls == []
    assert recorder.is_recording


def _meta(name: str) -> MeetingMeta:
    return MeetingMeta(
        f"2026-06-11_09-00_{name}",
        datetime(2026, 6, 11, 9, 0, tzinfo=UTC),
        name.title(),
    )

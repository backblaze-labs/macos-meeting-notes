"""Automatic Notes after transcription: optional, never a lockout."""

from __future__ import annotations

import queue
from pathlib import Path

from test_runtime_jobs import ImmediateThread
from test_tray import FakePipeline, FakeRecorder, _settings

from meeting_memory.ui.controller import TrayController


def _controller(tmp_path: Path, **overrides) -> TrayController:
    options = dict(
        settings=_settings(tmp_path),
        recorder=FakeRecorder(tmp_path),
        pipeline=FakePipeline(),
        event_queue=queue.Queue(),
        thread_factory=ImmediateThread,
    )
    options.update(overrides)
    return TrayController(**options)


def test_auto_notes_do_nothing_when_notes_is_unconfigured(tmp_path: Path) -> None:
    controller = _controller(tmp_path, notes_generator=None)

    controller.auto_generate_notes(tmp_path / "missing-meeting")

    assert controller.notes_available is False
    assert controller.drain_events() == []


def test_auto_notes_do_nothing_while_notes_is_paused(tmp_path: Path) -> None:
    controller = _controller(
        tmp_path, notes_generator=lambda p: p / "notes.md", notes_allowed=lambda: False
    )

    controller.auto_generate_notes(tmp_path / "missing-meeting")

    assert controller.notes_available is False
    assert controller.drain_events() == []


def test_auto_notes_attempt_confirmation_when_notes_is_available(tmp_path: Path) -> None:
    controller = _controller(tmp_path, notes_generator=lambda p: p / "notes.md")

    controller.auto_generate_notes(tmp_path / "missing-meeting")

    assert controller.notes_available is True
    assert [event.title for event in controller.drain_events()] == ["Notes skipped"]

"""Runtime Notes error reporting."""

from __future__ import annotations

import logging

from test_runtime_jobs import ImmediateThread

from meeting_memory.service.runtime_notes_gate import RuntimeNotesGate


def test_notes_failure_logs_a_safe_error_type(tmp_path, caplog) -> None:
    events: list[object] = []

    def failed(_path):
        raise RuntimeError("notes test failure")

    with caplog.at_level(logging.ERROR, logger="meeting_memory.service.runtime_notes_gate"):
        RuntimeNotesGate(failed, events.append, ImmediateThread, lambda: True).start(tmp_path)

    assert events[0].title == "Notes generation failed"
    assert caplog.records[0].message == "Notes generation failed error_type=RuntimeError"
    assert caplog.records[0].exc_info is None


def test_gate_is_unavailable_without_a_generator_or_while_paused(tmp_path) -> None:
    unconfigured = RuntimeNotesGate(None, lambda _e: None, ImmediateThread, lambda: True)
    paused = RuntimeNotesGate(lambda p: p, lambda _e: None, ImmediateThread, lambda: False)
    ready = RuntimeNotesGate(lambda p: p, lambda _e: None, ImmediateThread, lambda: True)

    assert unconfigured.available is False
    assert paused.available is False
    assert ready.available is True

    ready.set_enabled(False)

    assert ready.available is False

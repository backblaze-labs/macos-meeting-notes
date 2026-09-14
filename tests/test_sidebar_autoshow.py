"""Calendar-triggered sidebar visibility.

Kept out of test_tray.py so that file stays under the 300-line structure cap;
reuses its fakes via import, the same way test_sidebar_view_model.py does.
"""

from __future__ import annotations

import queue
from datetime import UTC, datetime
from pathlib import Path

from test_tray import FakePipeline, FakeRecorder, ImmediateThread, _settings
from tray_fakes import FakeRumps

from meeting_memory.types.events import MeetingDetected, SidebarHideRequested
from meeting_memory.ui.tray import RumpsTrayApp, TrayController


def test_start_recording_does_not_emit_a_sidebar_reveal(tmp_path: Path) -> None:
    event_queue: queue.Queue[object] = queue.Queue()
    controller = TrayController(
        settings=_settings(tmp_path),
        recorder=FakeRecorder(tmp_path),
        pipeline=FakePipeline(),
        event_queue=event_queue,
        thread_factory=ImmediateThread,
    )

    controller.start_recording("Product Sync")

    assert controller.drain_events() == []


def test_calendar_meeting_reveals_the_sidebar_and_stop_hides_it(tmp_path: Path) -> None:
    controller = TrayController(
        settings=_settings(tmp_path),
        recorder=FakeRecorder(tmp_path),
        pipeline=FakePipeline(),
        event_queue=queue.Queue(),
    )
    app = RumpsTrayApp(controller, rumps_module=FakeRumps())

    reveals: list[int] = []
    hides: list[int] = []
    app.sidebar.reveal = lambda: reveals.append(1)
    app.sidebar.hide = lambda: hides.append(1)
    app.handle_event(
        MeetingDetected("event", "Standup", datetime(2026, 6, 11, 9, tzinfo=UTC), "meet")
    )
    app.handle_event(SidebarHideRequested())

    assert reveals == [1]
    assert hides == [1]

"""Auto-show on record start — see docs/features/sidebar/completed/07-cutover.md.

Kept out of test_tray.py so that file stays under the 300-line structure cap;
reuses its fakes via import, the same way test_sidebar_view_model.py does.
"""

from __future__ import annotations

import queue
from pathlib import Path

from test_tray import FakePipeline, FakeRecorder, ImmediateThread, _settings
from tray_fakes import FakeRumps

from meeting_memory.types.events import SidebarRevealRequested
from meeting_memory.ui.tray import RumpsTrayApp, TrayController


def test_start_recording_emits_a_sidebar_reveal(tmp_path: Path) -> None:
    # The controller must emit the reveal as a queued event, never touch UI
    # from the worker callback (ARCHITECTURE.md threading model).
    event_queue: queue.Queue[object] = queue.Queue()
    controller = TrayController(
        settings=_settings(tmp_path),
        recorder=FakeRecorder(tmp_path),
        pipeline=FakePipeline(),
        event_queue=event_queue,
        thread_factory=ImmediateThread,
    )

    controller.start_recording("Product Sync")

    # Reveal fires first, before any stop-reminder the same start may queue.
    assert controller.drain_events()[0] == SidebarRevealRequested()


def test_sidebar_reveal_event_is_routed_to_the_sidebar(tmp_path: Path) -> None:
    controller = TrayController(
        settings=_settings(tmp_path),
        recorder=FakeRecorder(tmp_path),
        pipeline=FakePipeline(),
        event_queue=queue.Queue(),
    )
    app = RumpsTrayApp(controller, rumps_module=FakeRumps())

    reveals = []
    app.sidebar.reveal = lambda: reveals.append(1)
    app.handle_event(SidebarRevealRequested())

    assert reveals == [1]

"""Research-driven sidebar refinements (docs/deferred-work.md, 2026-09-06):
the menu-bar recording dot and the notification "Record" action that also
opens the call link."""

from __future__ import annotations

import queue
from pathlib import Path

from sidebar_view_model_fixtures import idle_view_model
from sidebar_wiring_fakes import FakePanel, _FakeController
from test_tray import FakePipeline, FakeRecorder, _settings
from tray_fakes import FakeClickAppKit, FakeRumps

from meeting_memory.ui.sidebar_tray_wiring import SidebarWiring
from meeting_memory.ui.tray import RumpsTrayApp, TrayController


def _app(tmp_path: Path) -> RumpsTrayApp:
    controller = TrayController(
        settings=_settings(tmp_path),
        recorder=FakeRecorder(tmp_path),
        pipeline=FakePipeline(),
        event_queue=queue.Queue(),
    )
    return RumpsTrayApp(controller, rumps_module=FakeRumps())


def test_record_notification_action_also_opens_the_meeting_link(tmp_path: Path) -> None:
    app = _app(tmp_path)
    urls: list[str] = []
    app.open_url = urls.append

    app.handle_notification(
        {"action": "start_recording", "calendar_title": "Standup", "meeting_url": "https://meet"}
    )
    assert urls == ["https://meet"]
    assert app.controller.recorder.started_title == "Standup"

    plain = _app(tmp_path)  # no link in the payload: nothing to open
    plain.open_url = urls.append
    plain.handle_notification({"action": "start_recording", "calendar_title": "Ad hoc"})
    assert urls == ["https://meet"]


def test_menu_bar_dot_tracks_recording_state_without_repeating() -> None:
    click_appkit = FakeClickAppKit()
    wiring = SidebarWiring(None, panel_factory=FakePanel, click_appkit=click_appkit)
    wiring.install_once(FakeRumps.App(name="Test"), FakeRumps())
    wiring.rebuild(idle_view_model())

    wiring.tick(_FakeController(is_recording=True, duration=1))
    wiring.tick(_FakeController(is_recording=True, duration=2))
    wiring.tick(_FakeController(is_recording=False))

    assert click_appkit.indicator_states == [True, False]

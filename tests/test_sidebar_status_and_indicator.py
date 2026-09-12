"""Menu-bar recording indicator and the notification "Record" action that
also opens the call link."""

from __future__ import annotations

import queue
from datetime import UTC, datetime
from pathlib import Path

from test_tray import FakePipeline, FakeRecorder, _settings
from tray_fakes import FakeRumps

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


def test_status_bar_shows_a_dot_and_timer_only_while_recording(tmp_path: Path) -> None:
    started = datetime(2026, 6, 11, 9, 0, tzinfo=UTC)
    recorder = FakeRecorder(tmp_path)
    controller = TrayController(
        settings=_settings(tmp_path),
        recorder=recorder,
        pipeline=FakePipeline(),
        event_queue=queue.Queue(),
        now=lambda: started.replace(second=7),
    )
    app = RumpsTrayApp(controller, rumps_module=FakeRumps())
    assert app.app.title is None

    recorder.start("Standup")
    app.drain_events()
    assert app.app.title == "\u25cf 00:07"
    assert app.menu_items.recording.title == "\u25a0 Stop Recording · 00:07"

    recorder.recording_warning = "microphone missing"
    app.drain_events()
    assert app.app.title == "\u26a0\ufe0e 00:07"

    recorder.stop()
    app.drain_events()
    assert app.app.title is None
    assert app.menu_items.recording.title == "\u25b6 Start Recording"

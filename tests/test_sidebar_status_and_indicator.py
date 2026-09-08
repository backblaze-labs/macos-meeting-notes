"""Research-driven sidebar refinements (docs/deferred-work.md, 2026-09-06):
the post-stop status row, the menu-bar recording dot, and the notification
"Record" action that also opens the call link."""

from __future__ import annotations

import queue
from pathlib import Path

from sidebar_view_model_fixtures import idle_view_model
from sidebar_wiring_fakes import FakePanel, _FakeController
from test_tray import FakePipeline, FakeRecorder, _settings
from tray_fakes import FakeClickAppKit, FakeRumps

from meeting_memory.types.events import NotifyEvent, RecordingCommitted, TranscriptReady
from meeting_memory.types.meeting import MeetingRef
from meeting_memory.ui.sidebar_tray_wiring import SidebarWiring
from meeting_memory.ui.sidebar_view_model import SidebarViewModel
from meeting_memory.ui.tray import RumpsTrayApp, TrayController


def _app(tmp_path: Path) -> RumpsTrayApp:
    controller = TrayController(
        settings=_settings(tmp_path),
        recorder=FakeRecorder(tmp_path),
        pipeline=FakePipeline(),
        event_queue=queue.Queue(),
    )
    return RumpsTrayApp(controller, rumps_module=FakeRumps())


def test_status_row_follows_the_latest_lifecycle_event(tmp_path: Path) -> None:
    app = _app(tmp_path)
    opened: list[Path] = []
    app.controller.opener = opened.append
    meeting = MeetingRef("2026-09-06_10-00_sync", "Product Sync", tmp_path)
    assert app.view_model.status is None

    app.handle_event(RecordingCommitted(meeting))
    status = app.view_model.status
    assert status.label == "Recording saved · Product Sync · audio saved locally"
    assert status.enabled is True
    status.action()
    assert opened == [tmp_path]

    app.handle_event(NotifyEvent("Meeting ending", "Product Sync is ending now. Stop recording?"))
    status = app.view_model.status
    assert status.label.startswith("Meeting ending · ")
    assert status.enabled is False and status.action is None


def test_transcript_ready_status_row_opens_speaker_review(tmp_path: Path) -> None:
    app = _app(tmp_path)
    reviewed: list[Path] = []
    app.open_speaker_review = reviewed.append
    meeting = MeetingRef("2026-09-06_10-00_sync", "Product Sync", tmp_path)

    app.handle_event(TranscriptReady(meeting))
    app.view_model.status.action()

    assert reviewed == [tmp_path]
    assert app.view_model.status.tooltip.endswith("Click to review speakers.")


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


def test_status_row_is_optional_on_the_view_model() -> None:
    assert SidebarViewModel.__dataclass_fields__["status"].default is None

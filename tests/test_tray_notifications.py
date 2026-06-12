"""Tests for tray notification actions and recent-meeting refresh."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from meeting_memory.types.events import MeetingDetected, NotifyEvent
from meeting_memory.types.meeting import RecentMeeting
from meeting_memory.ui import menu
from meeting_memory.ui.tray import RumpsTrayApp


def test_completion_notification_refreshes_recent_menu(tmp_path: Path) -> None:
    controller = FakeController(tmp_path)
    app = RumpsTrayApp(controller, rumps_module=FakeRumps())

    assert menu.NO_MEETINGS_LABEL in _menu_titles(app)

    controller.recent = [_recent(tmp_path)]
    app.handle_event(NotifyEvent("Meeting ready", "Done", meeting_directory=tmp_path))

    assert menu.recent_meeting_label(controller.recent[0]) in _menu_titles(app)


def test_meeting_notification_uses_record_action(tmp_path: Path) -> None:
    fake_rumps = FakeRumps()
    controller = FakeController(tmp_path)
    app = RumpsTrayApp(controller, rumps_module=fake_rumps)
    starts_at = datetime(2026, 6, 11, 9, 5, tzinfo=UTC)

    app.handle_event(MeetingDetected("event", "Standup", starts_at, "meet"))
    app.handle_notification({"action": "start_recording", "calendar_title": "Standup"})

    assert fake_rumps.notification_options[0]["action_button"] == "Record"
    assert controller.started_title == "Standup"
    assert controller.remembered[0].calendar_title == "Standup"


def test_stop_notification_uses_stop_action(tmp_path: Path) -> None:
    fake_rumps = FakeRumps()
    controller = FakeController(tmp_path)
    app = RumpsTrayApp(controller, rumps_module=fake_rumps)

    app.handle_event(
        NotifyEvent("Meeting ending", "Stop?", action_label="Stop", action="stop_recording")
    )

    assert fake_rumps.notification_options[0]["action_button"] == "Stop"
    assert fake_rumps.notification_options[0]["data"] == {"action": "stop_recording"}


def _menu_titles(app: RumpsTrayApp) -> list[str]:
    return [item.title for item in app.app.menu.items if item is not None]


def _recent(tmp_path: Path) -> RecentMeeting:
    return RecentMeeting(
        slug="2026-06-11_09-00_product-sync",
        calendar_title="Product Sync",
        started_at=datetime(2026, 6, 11, 9, 0, tzinfo=UTC),
        directory=tmp_path,
        markdown_path=tmp_path / "meeting.md",
    )


@dataclass
class FakeRecorder:
    is_recording: bool = False
    active_session: object | None = None


@dataclass
class FakeController:
    tmp_path: Path
    recorder: FakeRecorder = field(default_factory=FakeRecorder)
    recent: list[RecentMeeting] = field(default_factory=list)
    started_title: str | None = None
    remembered: list[MeetingDetected] = field(default_factory=list)

    def recent_meetings(self) -> list[RecentMeeting]:
        return self.recent

    def recording_duration_seconds(self) -> int:
        return 0

    def open_meeting(self, meeting: RecentMeeting) -> None:
        pass

    def open_meetings_folder(self) -> None:
        pass

    def sync_to_b2(self) -> None:
        pass

    def start_recording(self, calendar_title: str = "Untitled", *, ends_at=None) -> None:
        del ends_at
        self.started_title = calendar_title

    def stop_recording(self) -> None:
        pass

    def recording_context(self):
        return None

    def remember_meeting(self, event: MeetingDetected) -> None:
        self.remembered.append(event)

    def drain_events(self) -> list[object]:
        return []


class FakeMenu:
    def __init__(self):
        self.items = []

    def clear(self) -> None:
        self.items.clear()

    def add(self, item) -> None:
        self.items.append(item)


class FakeRumps:
    def __init__(self):
        self.notifications = []
        self.notification_options = []

    class MenuItem:
        def __init__(self, title, callback=None):
            self.title = title
            self.callback = callback

    class Timer:
        def __init__(self, callback, interval):
            self.callback = callback
            self.interval = interval

        def start(self) -> None:
            pass

    class App:
        def __init__(self, name, title=None, icon=None, template=None, quit_button="Quit"):
            self.name = name
            self.title = title
            self.icon = icon
            self.template = template
            self.quit_button = quit_button
            self.menu = FakeMenu()

        def run(self) -> None:
            pass

    def notification(self, title, subtitle, message, **kwargs) -> None:
        self.notifications.append((title, subtitle, message))
        self.notification_options.append(kwargs)

    def quit_application(self, _sender=None) -> None:
        pass

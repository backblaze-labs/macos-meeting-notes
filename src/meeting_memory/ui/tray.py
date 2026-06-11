"""macOS tray integration."""

from __future__ import annotations

import queue
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from meeting_memory.config.settings import Settings
from meeting_memory.doctor import CheckResult
from meeting_memory.service.pipeline import Pipeline
from meeting_memory.service.recorder import RecorderService
from meeting_memory.service.storage import list_recent_meetings
from meeting_memory.types.events import MeetingDetected, NotifyEvent
from meeting_memory.types.meeting import RecentMeeting
from meeting_memory.ui import menu
from meeting_memory.ui.preferences import open_preferences_window

EventQueue = queue.Queue[object]
ThreadFactory = Callable[..., threading.Thread]


@dataclass
class TrayController:
    settings: Settings
    recorder: RecorderService
    pipeline: Pipeline
    event_queue: EventQueue = field(default_factory=queue.Queue)
    opener: Callable[[Path], None] = field(default_factory=lambda: open_in_finder)
    sync_runner: Callable[[], object] | None = None
    thread_factory: ThreadFactory = threading.Thread

    def start_recording(self, calendar_title: str = "Untitled") -> None:
        self.recorder.start(calendar_title=calendar_title)

    def stop_recording(self) -> None:
        result = self.recorder.stop()
        if result is None:
            return
        thread = self.thread_factory(
            target=self.pipeline.run,
            args=(result.audio_path, result.meta),
            daemon=True,
        )
        thread.start()

    def sync_to_b2(self) -> None:
        if self.sync_runner is None:
            return
        thread = self.thread_factory(target=self.sync_runner, daemon=True)
        thread.start()

    def recent_meetings(self) -> list[RecentMeeting]:
        return list_recent_meetings(self.settings.meetings_dir_path)

    def open_meetings_folder(self) -> None:
        self.settings.meetings_dir_path.mkdir(parents=True, exist_ok=True)
        self.opener(self.settings.meetings_dir_path)

    def open_meeting(self, meeting: RecentMeeting) -> None:
        self.opener(meeting.directory)

    def drain_events(self) -> list[object]:
        events: list[object] = []
        while True:
            try:
                events.append(self.event_queue.get_nowait())
            except queue.Empty:
                return events


class RumpsTrayApp:
    def __init__(
        self,
        controller: TrayController,
        *,
        doctor_results: list[CheckResult] | None = None,
        rumps_module=None,
    ) -> None:
        self.rumps = rumps_module or _load_rumps()
        self.controller = controller
        self.doctor_results = doctor_results or []
        self.app = self.rumps.App("Meeting Memory", title="●")
        self.timer = self.rumps.Timer(self.drain_events, 1)
        self.rebuild_menu()

    def run(self) -> None:
        self.timer.start()
        self.app.run()

    def rebuild_menu(self, _sender=None) -> None:
        self.app.menu.clear()
        self.app.menu.add(self.rumps.MenuItem(menu.APP_TITLE, callback=None))
        self.app.menu.add(None)
        self.app.menu.add(
            self.rumps.MenuItem(
                menu.recording_label(is_recording=self.controller.recorder.is_recording),
                callback=self.toggle_recording,
            )
        )
        self.app.menu.add(None)
        self.app.menu.add(self.rumps.MenuItem(menu.RECENT_HEADER, callback=None))
        for recent in self.controller.recent_meetings():
            self.app.menu.add(
                self.rumps.MenuItem(
                    menu.recent_meeting_label(recent),
                    callback=lambda _sender, item=recent: self.controller.open_meeting(item),
                )
            )
        if not self.controller.recent_meetings():
            self.app.menu.add(self.rumps.MenuItem(menu.NO_MEETINGS_LABEL, callback=None))
        self.app.menu.add(None)
        self.app.menu.add(self.rumps.MenuItem(menu.OPEN_MEETINGS_LABEL, self.open_meetings_folder))
        self.app.menu.add(self.rumps.MenuItem(menu.SYNC_LABEL, self.sync_to_b2))
        self.app.menu.add(None)
        for result in self.doctor_results:
            if not result.ok or result.warning:
                self.app.menu.add(self.rumps.MenuItem(f"Setup: {result.name}", callback=None))
        self.app.menu.add(self.rumps.MenuItem(menu.PREFERENCES_LABEL, self.open_preferences))
        self.app.menu.add(self.rumps.MenuItem(menu.QUIT_LABEL, self.rumps.quit_application))

    def toggle_recording(self, _sender=None) -> None:
        if self.controller.recorder.is_recording:
            self.controller.stop_recording()
        else:
            self.controller.start_recording()
        self.rebuild_menu()

    def open_meetings_folder(self, _sender=None) -> None:
        self.controller.open_meetings_folder()

    def sync_to_b2(self, _sender=None) -> None:
        self.controller.sync_to_b2()

    def open_preferences(self, _sender=None) -> None:
        open_preferences_window(self.controller.settings)

    def drain_events(self, _timer=None) -> None:
        for event in self.controller.drain_events():
            self.handle_event(event)

    def handle_event(self, event: object) -> None:
        if isinstance(event, NotifyEvent):
            self.rumps.notification(event.title, "", event.body)
        elif isinstance(event, MeetingDetected):
            minutes = max(
                0,
                round((event.starts_at - datetime.now().astimezone()).total_seconds() / 60),
            )
            self.rumps.notification(
                "Meeting starting soon",
                "",
                f"{event.calendar_title} starts in {minutes} minutes",
            )


def open_in_finder(path: Path) -> None:
    subprocess.run(["open", str(path)], check=False)


def _load_rumps():
    import rumps

    return rumps

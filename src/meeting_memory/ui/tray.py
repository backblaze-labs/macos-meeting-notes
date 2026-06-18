"""macOS tray integration."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from meeting_memory.doctor import CheckResult, run_checks
from meeting_memory.types.events import MeetingDetected, NotifyEvent
from meeting_memory.ui import menu
from meeting_memory.ui.controller import TrayController
from meeting_memory.ui.icons import tray_icon_path
from meeting_memory.ui.macos import hide_dock_icon, keep_timer_running_during_menu_tracking
from meeting_memory.ui.notifications import send_notification
from meeting_memory.ui.preferences import open_preferences_window
from meeting_memory.ui.title_prompt import ask_recording_title

LOGGER = logging.getLogger(__name__)


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
        if rumps_module is None:
            hide_dock_icon(LOGGER)
        self._register_notification_handler()
        self.app = self.rumps.App(
            "Meeting Memory",
            title=self.current_tray_title(),
            icon=tray_icon_path(),
            template=True,
            quit_button=None,
        )
        self.timer = self.rumps.Timer(self.drain_events, 1)
        self.recording_item = None
        self.recording_label = ""
        self.rebuild_menu()

    def run(self) -> None:
        self.timer.start()
        keep_timer_running_during_menu_tracking(self.timer, LOGGER)
        self.app.run()

    def rebuild_menu(self, _sender=None) -> None:
        self.app.menu.clear()
        self.app.menu.add(self.rumps.MenuItem(menu.APP_TITLE, callback=None))
        self.app.menu.add(None)
        self.recording_item = self.rumps.MenuItem(
            self.current_recording_label(),
            callback=self.toggle_recording,
        )
        self.recording_label = self.recording_item.title
        self.app.menu.add(self.recording_item)
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
        recovered_recordings = self.controller.recovered_recordings()
        if recovered_recordings:
            self.app.menu.add(self.rumps.MenuItem(menu.RECOVERED_HEADER, callback=None))
            for recovered in recovered_recordings:
                self.app.menu.add(
                    self.rumps.MenuItem(
                        menu.recovered_recording_label(recovered.meta.slug),
                        callback=lambda _sender, item=recovered: (
                            self.controller.process_recovered_recording(item)
                        ),
                    )
                )
            self.app.menu.add(None)
        self.app.menu.add(self.rumps.MenuItem(menu.OPEN_MEETINGS_LABEL, self.open_meetings_folder))
        self.app.menu.add(self.rumps.MenuItem(menu.SYNC_LABEL, self.sync_to_b2))
        self.app.menu.add(
            self.rumps.MenuItem(menu.RETRY_PROCESSING_LABEL, self.retry_failed_processing)
        )
        self.app.menu.add(None)
        for result in self.doctor_results:
            if not result.ok or result.warning:
                self.app.menu.add(self.rumps.MenuItem(f"Setup: {result.name}", callback=None))
        self.app.menu.add(self.rumps.MenuItem(menu.RUN_DIAGNOSTICS_LABEL, self.run_diagnostics))
        self.app.menu.add(
            self.rumps.MenuItem(menu.TEST_NOTIFICATION_LABEL, self.send_test_notification)
        )
        self.app.menu.add(self.rumps.MenuItem(menu.PREFERENCES_LABEL, self.open_preferences))
        self.app.menu.add(self.rumps.MenuItem(menu.QUIT_LABEL, self.rumps.quit_application))

    def toggle_recording(self, _sender=None) -> None:
        if self.controller.recorder.is_recording:
            self.controller.stop_recording()
        else:
            context = self.controller.recording_context()
            if context is None:
                title = ask_recording_title(self.rumps)
                if title is None:
                    return
                self.controller.start_recording(title)
            else:
                self.controller.start_recording(context.calendar_title, ends_at=context.ends_at)
        self.rebuild_menu()

    def open_meetings_folder(self, _sender=None) -> None:
        self.controller.open_meetings_folder()

    def sync_to_b2(self, _sender=None) -> None:
        self.controller.sync_to_b2()

    def retry_failed_processing(self, _sender=None) -> None:
        self.controller.retry_failed_processing()

    def open_preferences(self, _sender=None) -> None:
        open_preferences_window(self.controller.settings)

    def run_diagnostics(self, _sender=None) -> None:
        self.doctor_results = run_checks()
        failures = [result for result in self.doctor_results if not result.ok or result.warning]
        if failures:
            body = "; ".join(f"{result.name}: {result.message}" for result in failures[:3])
            if len(failures) > 3:
                body = f"{body}; {len(failures) - 3} more"
        else:
            body = "All checks passed."
        self._send_notification("Meeting Memory diagnostics", "", body)
        self.rebuild_menu()

    def send_test_notification(self, _sender=None) -> None:
        self._send_notification(
            "Meeting Memory test",
            "",
            "Notifications are working.",
        )

    def drain_events(self, _timer=None) -> None:
        for event in self.controller.drain_events():
            self.handle_event(event)
        self.update_tray_title()
        self.update_recording_label()

    def current_tray_title(self) -> str | None:
        return menu.tray_title(
            is_recording=self.controller.recorder.is_recording,
            duration_seconds=self.controller.recording_duration_seconds(),
        )

    def update_tray_title(self) -> None:
        title = self.current_tray_title()
        if self.app.title != title:
            self.app.title = title

    def current_recording_label(self) -> str:
        return menu.recording_label(
            is_recording=self.controller.recorder.is_recording,
            duration_seconds=self.controller.recording_duration_seconds(),
        )

    def update_recording_label(self) -> None:
        if self.recording_item is None:
            return

        label = self.current_recording_label()
        if label == self.recording_label:
            return

        self.recording_item.title = label
        self.recording_label = label

    def handle_event(self, event: object) -> None:
        if isinstance(event, NotifyEvent):
            self.notify_event(event)
            if event.meeting_directory is not None:
                self.rebuild_menu()
        elif isinstance(event, MeetingDetected):
            self.controller.remember_meeting(event)
            self.notify_meeting_detected(event)

    def notify_event(self, event: NotifyEvent) -> None:
        kwargs = {}
        if event.action_label:
            kwargs["action_button"] = event.action_label
        if event.action:
            kwargs["data"] = {"action": event.action}
        if event.meeting_directory is not None:
            kwargs["data"] = {
                "action": "open_meeting",
                "meeting_directory": str(event.meeting_directory),
            }
        self._send_notification(event.title, "", event.body, **kwargs)

    def notify_meeting_detected(self, event: MeetingDetected) -> None:
        minutes = max(
            0,
            round((event.starts_at - datetime.now().astimezone()).total_seconds() / 60),
        )
        self._send_notification(
            "Meeting starting soon",
            "",
            f"{event.calendar_title} starts in {minutes} minutes",
            action_button="Record",
            data={
                "action": "start_recording",
                "calendar_title": event.calendar_title,
                "ends_at": event.ends_at.isoformat() if event.ends_at is not None else "",
            },
        )

    def handle_notification(self, data) -> None:
        if not isinstance(data, dict):
            return
        if data.get("action") == "start_recording":
            self.controller.start_recording(
                str(data.get("calendar_title") or "Untitled"),
                ends_at=_parse_datetime(data.get("ends_at")),
            )
            self.rebuild_menu()
        elif data.get("action") == "stop_recording":
            self.controller.stop_recording()
            self.rebuild_menu()
        elif data.get("action") == "open_meeting":
            directory = data.get("meeting_directory")
            if directory:
                self.controller.opener(Path(str(directory)))

    def _register_notification_handler(self) -> None:
        register = getattr(self.rumps, "notifications", None)
        if callable(register):
            register(self.handle_notification)

    def _send_notification(self, title: str, subtitle: str, message: str, **kwargs) -> None:
        send_notification(self.rumps, title, subtitle, message, LOGGER, **kwargs)


def _parse_datetime(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _load_rumps():
    import rumps

    return rumps

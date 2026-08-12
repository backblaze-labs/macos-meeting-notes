"""Setup-only tray app shown when full runtime settings are incomplete."""

from __future__ import annotations

import logging
import queue

from meeting_memory.service.configuration_surface import ConfigurationSurfaceCoordinator
from meeting_memory.service.readiness import checking_readiness_report
from meeting_memory.types.capabilities import ReadinessReport
from meeting_memory.types.events import NotifyEvent, ReadinessChecked
from meeting_memory.ui import menu
from meeting_memory.ui.configuration_surface import ConfigurationSurfaceUI
from meeting_memory.ui.icons import tray_icon_path
from meeting_memory.ui.macos import (
    allow_foreground_notifications,
    configure_background_app_identity,
    configure_modern_notifications,
)
from meeting_memory.ui.notifications import send_notification
from meeting_memory.ui.setup_readiness import (
    ReadinessCheck,
    readiness_menu_label,
    readiness_notification_body,
    readiness_tooltip,
)
from meeting_memory.ui.submenus import configuration_submenu, configuration_surface_actions

LOGGER = logging.getLogger(__name__)
SETUP_HEADER = "Setup Required"
SETUP_HINT = "Configure Recording Core and required Backblaze B2 backup"


class RumpsSetupApp:
    def __init__(
        self,
        *,
        readiness_report: ReadinessReport | None = None,
        rumps_module=None,
        configuration_surface: ConfigurationSurfaceCoordinator | None = None,
    ):
        self.rumps = rumps_module or _load_rumps()
        self.readiness_report = readiness_report
        self.event_queue: queue.Queue[object] = queue.Queue()
        self.readiness_check = ReadinessCheck(self.event_queue.put)
        if rumps_module is None:
            configure_background_app_identity(LOGGER)
            allow_foreground_notifications(LOGGER)
            configure_modern_notifications(lambda _data: None, LOGGER)
        self.app = self.rumps.App(
            "Meeting Memory",
            title=None,
            icon=tray_icon_path(),
            template=True,
            quit_button=None,
        )
        self.timer = self.rumps.Timer(self.drain_events, 0.25)
        coordinator = (
            configuration_surface
            if configuration_surface is not None
            else ConfigurationSurfaceCoordinator(self.event_queue.put)
        )
        self.configuration_ui = ConfigurationSurfaceUI(
            coordinator,
            self.rumps,
            rebuild_menu=self.rebuild_menu,
        )
        self.rebuild_menu()

    def run(self) -> None:
        self.timer.start()
        self.app.run()

    def rebuild_menu(self, _sender=None) -> None:
        self.app.menu.clear()
        self.app.menu.add(self.rumps.MenuItem(menu.APP_TITLE, callback=None))
        self.app.menu.add(None)
        self.app.menu.add(self.rumps.MenuItem(SETUP_HEADER, callback=None))
        self.app.menu.add(self.rumps.MenuItem(SETUP_HINT, callback=None))
        self.app.menu.add(None)
        self.app.menu.add(
            configuration_submenu(
                self.rumps,
                None,
                configuration_surface_actions(self.configuration_ui),
                notes_prompt_available=False,
            )
        )
        self.app.menu.add(None)
        if self.readiness_report is None:
            self.app.menu.add(self.rumps.MenuItem("Run Check Setup below", callback=None))
        else:
            for status in self.readiness_report.statuses:
                item = self.rumps.MenuItem(readiness_menu_label(status), callback=None)
                item.tooltip = readiness_tooltip(status)
                self.app.menu.add(item)
        self.app.menu.add(None)
        self.app.menu.add(self.rumps.MenuItem(menu.RUN_DIAGNOSTICS_LABEL, self.run_diagnostics))
        self.app.menu.add(
            self.rumps.MenuItem(menu.TEST_NOTIFICATION_LABEL, self.send_test_notification)
        )
        self.app.menu.add(self.rumps.MenuItem(menu.QUIT_LABEL, self.rumps.quit_application))

    def run_diagnostics(self, _sender=None) -> None:
        if self.readiness_check.start() is not None:
            self.readiness_report = checking_readiness_report()
            self.rebuild_menu()

    def drain_events(self, _timer=None) -> None:
        while True:
            try:
                event = self.event_queue.get_nowait()
            except queue.Empty:
                return
            if self.configuration_ui.handle_event(event):
                continue
            if isinstance(event, ReadinessChecked) and self.readiness_check.acknowledge(
                event.operation_id
            ):
                self.readiness_report = event.report
                self._send_notification(
                    "Meeting Memory setup",
                    "",
                    readiness_notification_body(event.report),
                )
                self.rebuild_menu()
            elif isinstance(event, NotifyEvent):
                self._send_notification(event.title, "", event.body)

    def send_test_notification(self, _sender=None) -> None:
        self._send_notification("Meeting Memory test", "", "Notifications are working.")

    def _send_notification(self, title: str, subtitle: str, message: str) -> None:
        send_notification(self.rumps, title, subtitle, message, LOGGER)


def _load_rumps():
    import rumps

    return rumps

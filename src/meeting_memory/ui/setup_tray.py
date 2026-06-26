"""Setup-only tray app shown when full runtime settings are incomplete."""

from __future__ import annotations

import logging

from meeting_memory.doctor import CheckResult, run_checks
from meeting_memory.ui import menu
from meeting_memory.ui.icons import tray_icon_path
from meeting_memory.ui.macos import (
    allow_foreground_notifications,
    configure_modern_notifications,
    hide_dock_icon,
)
from meeting_memory.ui.notifications import send_notification

LOGGER = logging.getLogger(__name__)
SETUP_HEADER = "Setup Required"
SETUP_HINT = "Run make setup, fill .env, then Run Diagnostics"


class RumpsSetupApp:
    def __init__(self, *, doctor_results: list[CheckResult] | None = None, rumps_module=None):
        self.rumps = rumps_module or _load_rumps()
        self.doctor_results = doctor_results or []
        if rumps_module is None:
            hide_dock_icon(LOGGER)
            allow_foreground_notifications(LOGGER)
            configure_modern_notifications(lambda _data: None, LOGGER)
        self.app = self.rumps.App(
            "Meeting Memory",
            title=None,
            icon=tray_icon_path(),
            template=True,
            quit_button=None,
        )
        self.rebuild_menu()

    def run(self) -> None:
        self.app.run()

    def rebuild_menu(self, _sender=None) -> None:
        self.app.menu.clear()
        self.app.menu.add(self.rumps.MenuItem(menu.APP_TITLE, callback=None))
        self.app.menu.add(None)
        self.app.menu.add(self.rumps.MenuItem(SETUP_HEADER, callback=None))
        self.app.menu.add(self.rumps.MenuItem(SETUP_HINT, callback=None))
        self.app.menu.add(None)
        failures = [result for result in self.doctor_results if not result.ok or result.warning]
        for result in failures:
            self.app.menu.add(self.rumps.MenuItem(f"Setup: {result.name}", callback=None))
        if not failures:
            self.app.menu.add(self.rumps.MenuItem("All checks passed. Restart app.", callback=None))
        self.app.menu.add(None)
        self.app.menu.add(self.rumps.MenuItem(menu.RUN_DIAGNOSTICS_LABEL, self.run_diagnostics))
        self.app.menu.add(
            self.rumps.MenuItem(menu.TEST_NOTIFICATION_LABEL, self.send_test_notification)
        )
        self.app.menu.add(self.rumps.MenuItem(menu.QUIT_LABEL, self.rumps.quit_application))

    def run_diagnostics(self, _sender=None) -> None:
        self.doctor_results = run_checks()
        failures = [result for result in self.doctor_results if not result.ok or result.warning]
        if failures:
            body = "; ".join(f"{result.name}: {result.message}" for result in failures[:3])
            if len(failures) > 3:
                body = f"{body}; {len(failures) - 3} more"
        else:
            body = "All checks passed. Restart Meeting Memory."
        self._send_notification("Meeting Memory setup", "", body)
        self.rebuild_menu()

    def send_test_notification(self, _sender=None) -> None:
        self._send_notification("Meeting Memory test", "", "Notifications are working.")

    def _send_notification(self, title: str, subtitle: str, message: str) -> None:
        send_notification(self.rumps, title, subtitle, message, LOGGER)


def _load_rumps():
    import rumps

    return rumps

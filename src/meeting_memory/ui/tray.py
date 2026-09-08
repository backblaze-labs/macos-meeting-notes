"""macOS tray integration.

The status item is an icon-only toggle for the floating sidebar panel
(`docs/features/sidebar.md`); nothing is rendered in the menu bar itself and
the runtime app owns no `NSMenu`. Every state change funnels through
`refresh_sidebar()`, which rebuilds the panel from one immutable
`SidebarViewModel` snapshot.
"""

from __future__ import annotations

import logging
import webbrowser
from pathlib import Path
from typing import Any

from meeting_memory.service.configuration_surface import ConfigurationSurfaceCoordinator
from meeting_memory.service.readiness import checking_readiness_report
from meeting_memory.service.screenshots import ScreenshotStore
from meeting_memory.types.capabilities import ReadinessReport
from meeting_memory.types.events import (
    MeetingDetected,
    NotifyEvent,
    ReadinessChecked,
    RecordingTitleNeeded,
    SidebarRevealRequested,
)
from meeting_memory.ui import load_rumps
from meeting_memory.ui.audio_modes import AudioModeMenu
from meeting_memory.ui.configuration_surface import ConfigurationSurfaceUI
from meeting_memory.ui.controller import TrayController
from meeting_memory.ui.icons import tray_icon_path
from meeting_memory.ui.macos import (
    allow_foreground_notifications,
    configure_background_app_identity,
    configure_modern_notifications,
    keep_timer_running_during_menu_tracking,
)
from meeting_memory.ui.notifications import (
    meeting_detected_notification,
    notify_event_kwargs,
    parse_notification_candidates,
    parse_notification_datetime,
    send_notification,
)
from meeting_memory.ui.recording_health import RecordingHealthMonitor
from meeting_memory.ui.runtime_events import runtime_notification
from meeting_memory.ui.screenshot_actions import ScreenshotActions
from meeting_memory.ui.screenshot_hotkey import GlobalHotkey
from meeting_memory.ui.setup_readiness import readiness_check_for, readiness_notification_body
from meeting_memory.ui.sidebar_tray_wiring import SidebarWiring
from meeting_memory.ui.sidebar_view_model import (
    DebuggingActions,
    RowView,
    SidebarViewModel,
    build_view_model,
)
from meeting_memory.ui.speaker_review import SpeakerReviewActions, open_speaker_review_window
from meeting_memory.ui.submenus import configuration_surface_actions
from meeting_memory.ui.title_prompt import ask_recording_title

LOGGER = logging.getLogger(__name__)


class RumpsTrayApp:
    def __init__(
        self,
        controller: TrayController,
        *,
        readiness_report: ReadinessReport | None = None,
        rumps_module=None,
        configuration_surface: ConfigurationSurfaceCoordinator | None = None,
        sidebar_panel_factory: Any = None,
        sidebar_click_appkit: Any = None,
        screenshot_store: ScreenshotStore | None = None,
    ) -> None:
        self.rumps = rumps_module or load_rumps()
        self.controller = controller
        self.readiness_report = readiness_report
        self.readiness_check = readiness_check_for(controller)
        if rumps_module is None:
            configure_background_app_identity(LOGGER)
            allow_foreground_notifications(LOGGER)
            configure_modern_notifications(self.handle_notification, LOGGER)
        register = getattr(self.rumps, "notifications", None)
        if callable(register):
            register(self.handle_notification)
        # title=None: the menu bar item carries no state — no timer, no
        # warning glyph. Recording state lives in the sidebar, which
        # `SidebarRevealRequested` forces visible when a recording starts.
        self.app = self.rumps.App(
            "Meeting Memory",
            title=None,
            icon=tray_icon_path(),
            template=True,
            quit_button=None,
        )
        self.timer = self.rumps.Timer(self.drain_events, 1)
        self.screenshots = ScreenshotActions(controller, screenshot_store)
        self.screenshot_hotkey = None if rumps_module else GlobalHotkey(self.take_screenshot)
        self.sidebar = SidebarWiring(
            rumps_module,
            on_toggle_recording=self.toggle_recording,
            on_quit=self.rumps.quit_application,
            panel_factory=sidebar_panel_factory,
            click_appkit=sidebar_click_appkit,
        )
        self.view_model: SidebarViewModel | None = None
        self.last_status: NotifyEvent | None = None  # rendered as the sidebar's status row
        self.open_url = webbrowser.open  # swapped out by tests
        self.recording_health = RecordingHealthMonitor(controller.recorder, controller.event_queue)
        self.audio_mode_menu = AudioModeMenu(
            self.rumps, self.controller, on_change=self.refresh_sidebar
        )
        if configuration_surface is None:
            configuration_surface = ConfigurationSurfaceCoordinator(
                controller.event_queue.put, prompt_settings=controller.settings
            )
        self.configuration_ui = ConfigurationSurfaceUI(
            configuration_surface,
            self.rumps,
            rebuild_menu=self.refresh_sidebar,
        )
        self.refresh_sidebar()

    def run(self) -> None:
        if self.screenshot_hotkey is not None:
            self.screenshot_hotkey.install()
        self.timer.start()
        # The setup tray and the right-click Quit menu still track menus.
        keep_timer_running_during_menu_tracking(self.timer, LOGGER)
        self.app.run()

    def refresh_sidebar(self, _sender=None) -> None:
        """Rebuild the panel from a fresh snapshot of app state.

        The only render path. Called after every state change the tray
        knows about; the 1 Hz timer label update goes through
        `SidebarWiring.tick` instead, without a rebuild.
        """

        self.view_model = build_view_model(
            self.controller,
            readiness_report=self.readiness_report,
            audio_mode_menu=self.audio_mode_menu,
            configuration_actions=configuration_surface_actions(self.configuration_ui),
            debugging_actions=DebuggingActions(
                review_speakers=self.open_speaker_review,
                generate_notes=self.controller.generate_notes,
                process_recovered_recording=self.controller.process_recovered_recording,
                scan_legacy_recoveries=self.controller.scan_legacy_recoveries,
                sync_to_b2=self.controller.sync_to_b2,
                retry_failed_processing=self.controller.retry_failed_processing,
                run_diagnostics=self.run_diagnostics,
                send_test_notification=self.send_test_notification,
            ),
            status=self._status_row(),
        )
        self.sidebar.rebuild(self.view_model)

    def _status_row(self) -> RowView | None:
        """The latest lifecycle message as a row: clickable when it points at
        a meeting (Reveal / Review Speakers), otherwise a plain caption."""

        event = self.last_status
        if event is None:
            return None
        directory = event.meeting_directory
        action = None
        if directory is not None:
            if event.action == "review_speakers":
                action = lambda: self.open_speaker_review(directory)  # noqa: E731
            else:
                action = lambda: self.controller.opener(directory)  # noqa: E731
        return RowView(
            label=f"{event.title} · {event.body}",
            tooltip=f"{event.body}. Click to {event.action_label.lower()}."
            if action is not None and event.action_label
            else event.body,
            enabled=action is not None,
            action=action,
        )

    def toggle_recording(self, _sender=None) -> None:
        if self.controller.recorder.is_recording:
            self.controller.stop_recording()
        else:
            self.controller.start_recording()
        self.refresh_sidebar()

    def take_screenshot(self, _sender=None) -> None:
        self.screenshots.take()

    def open_speaker_review(self, meeting_path: Path) -> None:
        open_speaker_review_window(
            meeting_path,
            SpeakerReviewActions(
                load_review=self.controller.load_speaker_review,
                confirm_aliases=self.controller.confirm_speaker_aliases,
                keep_labels=self.controller.keep_speaker_labels,
                generate_notes=self.controller.generate_notes,
            ),
            rumps_module=self.rumps,
        )
        self.refresh_sidebar()

    def run_diagnostics(self, _sender=None) -> None:
        if self.readiness_check.start() is not None:
            self.readiness_report = checking_readiness_report()
            self.refresh_sidebar()

    def send_test_notification(self, _sender=None) -> None:
        self._send_notification("Meeting Memory test", "", "Notifications are working.")

    def drain_events(self, _timer=None) -> None:
        self.sidebar.install_once(self.app, self.rumps)
        self.recording_health.poll()
        for event in self.controller.drain_events():
            self.handle_event(event)
        self.sidebar.tick(self.controller)

    def handle_event(self, event: object) -> None:
        if self.configuration_ui.handle_event(event):
            return
        self.screenshots.handle_event(event)
        if isinstance(event, SidebarRevealRequested):
            self.sidebar.reveal()
            return
        if isinstance(event, ReadinessChecked) and self.readiness_check.acknowledge(
            event.operation_id
        ):
            self.readiness_report = event.report
            self._send_notification(
                "Meeting Memory setup", "", readiness_notification_body(event.report)
            )
            self.refresh_sidebar()
            return
        runtime_event = runtime_notification(event)
        if runtime_event is not None:
            self.last_status = runtime_event
            self.notify_event(runtime_event)
            self.refresh_sidebar()
            return
        if isinstance(event, NotifyEvent):
            self.last_status = event
            if event.show_notification:
                self.notify_event(event)
            self.refresh_sidebar()
        elif isinstance(event, RecordingTitleNeeded):
            self.prompt_for_recording_title(event)
        elif isinstance(event, MeetingDetected):
            self.controller.remember_meeting(event)
            self.notify_meeting_detected(event)

    def prompt_for_recording_title(self, event: RecordingTitleNeeded) -> None:
        title = ask_recording_title(self.rumps, default_title=event.meta.calendar_title)
        meta = event.meta.with_title(title) if title is not None else event.meta
        self.controller.process_recording(event.audio_path, meta, recovery=event.recovery)

    def notify_event(self, event: NotifyEvent) -> None:
        self._send_notification(event.title, "", event.body, **notify_event_kwargs(event))

    def notify_meeting_detected(self, event: MeetingDetected) -> None:
        title, message, kwargs = meeting_detected_notification(event)
        self._send_notification(title, "", message, **kwargs)

    def handle_notification(self, data) -> None:
        if not isinstance(data, dict):
            return
        if data.get("action") == "start_recording":
            self.controller.start_recording(
                str(data.get("calendar_title") or "Untitled"),
                ends_at=parse_notification_datetime(data.get("ends_at")),
                speaker_candidates=parse_notification_candidates(data.get("speaker_candidates")),
            )
            # One click does both, Granola-style: start recording *and* join.
            meeting_url = str(data.get("meeting_url") or "")
            if meeting_url:
                self.open_url(meeting_url)
            self.refresh_sidebar()
        elif data.get("action") == "stop_recording":
            self.controller.stop_recording()
            self.refresh_sidebar()
        elif data.get("action") == "open_meeting":
            directory = data.get("meeting_directory")
            if directory:
                self.controller.opener(Path(str(directory)))
        elif data.get("action") == "review_speakers":
            directory = data.get("meeting_directory")
            if directory:
                self.open_speaker_review(Path(str(directory)))

    def _send_notification(self, title: str, subtitle: str, message: str, **kwargs) -> None:
        send_notification(self.rumps, title, subtitle, message, LOGGER, **kwargs)

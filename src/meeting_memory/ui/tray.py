"""macOS tray integration."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from meeting_memory.service.configuration_surface import ConfigurationSurfaceCoordinator
from meeting_memory.service.readiness import checking_readiness_report
from meeting_memory.types.capabilities import ReadinessReport
from meeting_memory.types.events import (
    MeetingDetected,
    NotifyEvent,
    ReadinessChecked,
    RecordingTitleNeeded,
)
from meeting_memory.ui import load_rumps, menu
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
    notify_event_kwargs,
    parse_notification_candidates,
    parse_notification_datetime,
    send_notification,
)
from meeting_memory.ui.recording_health import RecordingHealthMonitor
from meeting_memory.ui.runtime_events import runtime_notification
from meeting_memory.ui.setup_readiness import readiness_check_for, readiness_notification_body
from meeting_memory.ui.speaker_review import SpeakerReviewActions, open_speaker_review_window
from meeting_memory.ui.submenus import (
    DebuggingActions,
    configuration_submenu,
    configuration_surface_actions,
    debugging_submenu,
)
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
    ) -> None:
        self.rumps = rumps_module or load_rumps()
        self.controller = controller
        self.readiness_report = readiness_report
        self.readiness_check = readiness_check_for(controller)
        if rumps_module is None:
            configure_background_app_identity(LOGGER)
            allow_foreground_notifications(LOGGER)
            configure_modern_notifications(self.handle_notification, LOGGER)
        self._register_notification_handler()
        self.app = self.rumps.App(
            "Meeting Memory",
            title=self._tray_title(),
            icon=tray_icon_path(),
            template=True,
            quit_button=None,
        )
        self.timer = self.rumps.Timer(self.drain_events, 1)
        self.recording_item = None
        self.recording_label = ""
        self.recording_health = RecordingHealthMonitor(controller.recorder, controller.event_queue)
        self.audio_mode_menu = AudioModeMenu(
            self.rumps, self.controller, rebuild_menu=self.rebuild_menu
        )  # noqa: E501
        if configuration_surface is None:
            configuration_surface = ConfigurationSurfaceCoordinator(
                controller.event_queue.put, prompt_settings=controller.settings
            )
        self.configuration_ui = ConfigurationSurfaceUI(
            configuration_surface,
            self.rumps,
            rebuild_menu=self.rebuild_menu,
        )
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
            self.current_recording_label(), self.toggle_recording
        )  # noqa: E501
        self.recording_label = self.recording_item.title
        self.app.menu.add(self.recording_item)
        self.app.menu.add(None)
        self.app.menu.add(self.rumps.MenuItem(menu.RECENT_HEADER, callback=None))
        recent_meetings = self.controller.recent_meetings()
        for recent in recent_meetings:
            self.app.menu.add(
                self.rumps.MenuItem(
                    menu.recent_meeting_label(recent),
                    callback=lambda _sender, item=recent: self.controller.open_meeting(item),
                )
            )
        if not recent_meetings:
            self.app.menu.add(self.rumps.MenuItem(menu.NO_MEETINGS_LABEL, callback=None))
        self.app.menu.add(None)
        self.app.menu.add(
            self.rumps.MenuItem(
                menu.OPEN_MEETINGS_LABEL,
                lambda _sender: self.controller.open_meetings_folder(),
            )
        )
        self.app.menu.add(None)
        self.app.menu.add(
            configuration_submenu(
                self.rumps,
                self.audio_mode_menu,
                configuration_surface_actions(self.configuration_ui),
            )
        )
        self.app.menu.add(self._debugging_submenu())
        self.app.menu.add(self.rumps.MenuItem(menu.QUIT_LABEL, self.rumps.quit_application))

    def _debugging_submenu(self):
        return debugging_submenu(
            self.rumps,
            processing_tasks=self.controller.pending_processing_tasks(),
            recovered_recordings=self.controller.recovered_recordings(),
            readiness_report=self.readiness_report,
            actions=DebuggingActions(
                review_speakers=self.open_speaker_review,
                generate_notes=self.controller.generate_notes,
                process_recovered_recording=self.controller.process_recovered_recording,
                scan_legacy_recoveries=self.controller.scan_legacy_recoveries,
                sync_to_b2=self.controller.sync_to_b2,
                retry_failed_processing=self.controller.retry_failed_processing,
                run_diagnostics=self.run_diagnostics,
                send_test_notification=self.send_test_notification,
            ),
        )

    def toggle_recording(self, _sender=None) -> None:
        if self.controller.recorder.is_recording:
            self.controller.stop_recording()
        else:
            self.controller.start_recording()
        self.rebuild_menu()

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
        self.rebuild_menu()

    def run_diagnostics(self, _sender=None) -> None:
        if self.readiness_check.start() is not None:
            self.readiness_report = checking_readiness_report()
            self.rebuild_menu()

    def send_test_notification(self, _sender=None) -> None:
        self._send_notification("Meeting Memory test", "", "Notifications are working.")

    def drain_events(self, _timer=None) -> None:
        self.recording_health.poll()
        for event in self.controller.drain_events():
            self.handle_event(event)
        self.update_tray_title()
        self.update_recording_label()

    def _tray_title(self) -> str | None:
        return menu.tray_title(
            is_recording=self.controller.recorder.is_recording,
            duration_seconds=self.controller.recording_duration_seconds(),
        )

    def update_tray_title(self) -> None:
        title = self._tray_title()
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
        if self.configuration_ui.handle_event(event):
            return
        if isinstance(event, ReadinessChecked) and self.readiness_check.acknowledge(
            event.operation_id
        ):
            self.readiness_report = event.report
            self._send_notification(
                "Meeting Memory setup", "", readiness_notification_body(event.report)
            )
            self.rebuild_menu()
            return
        runtime_event = runtime_notification(event)
        if runtime_event is not None:
            self.notify_event(runtime_event)
            self.rebuild_menu()
            return
        if isinstance(event, NotifyEvent):
            if event.show_notification:
                self.notify_event(event)
            if event.meeting_directory is not None or event.rebuild_menu:
                self.rebuild_menu()
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
                "speaker_candidates": ",".join(event.speaker_candidates),
            },
        )

    def handle_notification(self, data) -> None:
        if not isinstance(data, dict):
            return
        if data.get("action") == "start_recording":
            self.controller.start_recording(
                str(data.get("calendar_title") or "Untitled"),
                ends_at=parse_notification_datetime(data.get("ends_at")),
                speaker_candidates=parse_notification_candidates(data.get("speaker_candidates")),
            )
            self.rebuild_menu()
        elif data.get("action") == "stop_recording":
            self.controller.stop_recording()
            self.rebuild_menu()
        elif data.get("action") == "open_meeting":
            directory = data.get("meeting_directory")
            if directory:
                self.controller.opener(Path(str(directory)))
        elif data.get("action") == "review_speakers":
            directory = data.get("meeting_directory")
            if directory:
                self.open_speaker_review(Path(str(directory)))

    def _register_notification_handler(self) -> None:
        register = getattr(self.rumps, "notifications", None)
        if callable(register):
            register(self.handle_notification)

    def _send_notification(self, title: str, subtitle: str, message: str, **kwargs) -> None:
        send_notification(self.rumps, title, subtitle, message, LOGGER, **kwargs)

"""Tests for tray notification actions and the status-menu refresh."""

from __future__ import annotations

import queue
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from tray_fakes import FakeRumps, submenu_titles

from meeting_memory.types.events import MeetingDetected, NotifyEvent, TranscriptReady
from meeting_memory.types.meeting import MeetingRef, RecentMeeting
from meeting_memory.ui import menu
from meeting_memory.ui.tray import RumpsTrayApp


def test_silent_completion_event_refreshes_recent_menu(tmp_path: Path) -> None:
    fake_rumps = FakeRumps()
    controller = FakeController(tmp_path)
    app = RumpsTrayApp(controller, rumps_module=fake_rumps)

    assert menu.NO_MEETINGS_LABEL in _menu_titles(app)

    controller.recent = [_recent(tmp_path)]
    app.handle_event(
        NotifyEvent(
            "Meeting ready",
            "Done",
            meeting_directory=tmp_path,
            show_notification=False,
        )
    )

    assert menu.recent_meeting_label(controller.recent[0]) in _menu_titles(app)
    assert fake_rumps.notifications == []


def test_meeting_notification_uses_record_action(tmp_path: Path) -> None:
    fake_rumps = FakeRumps()
    controller = FakeController(tmp_path)
    app = RumpsTrayApp(controller, rumps_module=fake_rumps)
    starts_at = datetime(2026, 6, 11, 9, 5, tzinfo=UTC)

    app.handle_event(
        MeetingDetected(
            "event",
            "Standup",
            starts_at,
            "meet",
            speaker_candidates=("Casey", "Drew"),
        )
    )
    app.handle_notification(
        {
            "action": "start_recording",
            "calendar_title": "Standup",
            "speaker_candidates": "Casey,Drew",
        }
    )

    assert fake_rumps.notification_options[0]["action_button"] == "Record"
    assert controller.started_title == "Standup"
    assert controller.started_candidates == ("Casey", "Drew")
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


def test_transcript_ready_starts_notes_and_offers_open(tmp_path: Path) -> None:
    # No speaker-review step: the transcript's calendar attendees feed Notes.
    fake_rumps = FakeRumps()
    controller = FakeController(tmp_path)
    app = RumpsTrayApp(controller, rumps_module=fake_rumps)
    meeting = MeetingRef("2026-06-11_09-00_product-sync", "Product Sync", tmp_path)

    app.handle_event(TranscriptReady(meeting))

    assert controller.auto_notes == [tmp_path]
    assert fake_rumps.notifications[0][:2] == ("Transcript ready", "")
    assert fake_rumps.notifications[0][2] == "Product Sync · generating notes"
    assert fake_rumps.notification_options[0]["action_button"] == "Open"
    assert fake_rumps.notification_options[0]["data"] == {
        "action": "open_meeting",
        "meeting_directory": str(tmp_path),
    }


def test_open_meeting_notification_reveals_the_directory(tmp_path: Path) -> None:
    controller = FakeController(tmp_path)
    app = RumpsTrayApp(controller, rumps_module=FakeRumps())
    opened: list[Path] = []
    controller.opener = opened.append

    app.handle_notification({"action": "open_meeting", "meeting_directory": str(tmp_path)})
    app.handle_notification({"action": "review_speakers", "meeting_directory": str(tmp_path)})

    assert opened == [tmp_path]  # the retired review action is ignored


def test_debugging_submenu_has_no_pending_task_section(tmp_path: Path) -> None:
    app = RumpsTrayApp(FakeController(tmp_path), rumps_module=FakeRumps())

    debugging_titles = submenu_titles(app, menu.DEBUGGING_LABEL)

    assert debugging_titles == [
        menu.LEGACY_RECOVERY_SCAN_LABEL,
        menu.SYNC_LABEL,
        menu.RETRY_PROCESSING_LABEL,
        menu.RUN_DIAGNOSTICS_LABEL,
        menu.TEST_NOTIFICATION_LABEL,
    ]


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
    settings: object = field(default_factory=object)
    recorder: FakeRecorder = field(default_factory=FakeRecorder)
    event_queue: queue.Queue[object] = field(default_factory=queue.Queue)
    recent: list[RecentMeeting] = field(default_factory=list)
    started_title: str | None = None
    started_candidates: tuple[str, ...] = ()
    remembered: list[MeetingDetected] = field(default_factory=list)
    auto_notes: list[Path] = field(default_factory=list)
    opener: object = None

    def recent_meetings(self) -> list[RecentMeeting]:
        return self.recent

    def recovered_recordings(self) -> list[object]:
        return []

    def recording_duration_seconds(self) -> int:
        return 0

    def open_meeting(self, meeting: RecentMeeting) -> None:
        pass

    def open_meetings_folder(self) -> None:
        pass

    def sync_to_b2(self) -> None:
        pass

    def retry_failed_processing(self) -> None:
        pass

    def auto_generate_notes(self, path: Path) -> None:
        self.auto_notes.append(path)

    def process_recovered_recording(self, recording: object) -> None:
        pass

    def scan_legacy_recoveries(self) -> None:
        pass

    def start_recording(self, calendar_title: str, *, ends_at=None, speaker_candidates=()) -> None:
        self.started_title = calendar_title
        self.started_candidates = speaker_candidates

    def stop_recording(self) -> None:
        pass

    def remember_meeting(self, event: MeetingDetected) -> None:
        self.remembered.append(event)

    def drain_events(self) -> list[object]:
        events: list[object] = []
        while not self.event_queue.empty():
            events.append(self.event_queue.get_nowait())
        return events

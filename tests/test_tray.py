"""Tests for tray controller and event rendering."""

from __future__ import annotations

import queue
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tray_fakes import FakeRumps

from meeting_memory.config.settings import Settings
from meeting_memory.service.recorder import RecordingResult, RecordingSession
from meeting_memory.types.events import MeetingDetected, NotifyEvent
from meeting_memory.types.meeting import MeetingMeta
from meeting_memory.ui import menu
from meeting_memory.ui.tray import RumpsTrayApp, TrayController


def test_tray_controller_runs_pipeline_after_stop(tmp_path: Path) -> None:
    event_queue: queue.Queue[object] = queue.Queue()
    recorder = FakeRecorder(tmp_path)
    pipeline = FakePipeline()
    controller = TrayController(
        settings=_settings(tmp_path),
        recorder=recorder,
        pipeline=pipeline,
        event_queue=event_queue,
        thread_factory=ImmediateThread,
    )

    controller.start_recording("Product Sync")
    controller.stop_recording()

    assert recorder.started_title == "Product Sync"
    assert recorder.started_candidates == ()
    assert pipeline.calls == [(recorder.result.audio_path, recorder.result.meta)]
    assert controller.drain_events() == [
        NotifyEvent("Recording saved", "Product Sync · processing queued", show_notification=False)
    ]


def test_tray_controller_drains_events(tmp_path: Path) -> None:
    event_queue: queue.Queue[object] = queue.Queue()
    event_queue.put(NotifyEvent("Title", "Body"))
    controller = TrayController(
        settings=_settings(tmp_path),
        recorder=FakeRecorder(tmp_path),
        pipeline=FakePipeline(),
        event_queue=event_queue,
    )

    assert controller.drain_events() == [NotifyEvent("Title", "Body")]
    assert controller.drain_events() == []


def test_tray_controller_reports_start_recording_errors(tmp_path: Path) -> None:
    event_queue: queue.Queue[object] = queue.Queue()
    message = "Screen & System Audio permission is required"
    controller = TrayController(
        settings=_settings(tmp_path),
        recorder=FailingRecorder(message),
        pipeline=FakePipeline(),
        event_queue=event_queue,
        thread_factory=ImmediateThread,
    )

    controller.start_recording()

    assert controller.drain_events() == [NotifyEvent("Recording could not start", message)]


def test_tray_controller_reports_stop_recording_errors(tmp_path: Path) -> None:
    event_queue: queue.Queue[object] = queue.Queue()
    controller = TrayController(
        settings=_settings(tmp_path),
        recorder=FailingRecorder("native converter failed", is_recording=True),
        pipeline=FakePipeline(),
        event_queue=event_queue,
        thread_factory=ImmediateThread,
    )

    controller.stop_recording()

    assert controller.drain_events() == [
        NotifyEvent(title="Recording could not finish", body="native converter failed")
    ]


def test_tray_controller_calculates_recording_duration(tmp_path: Path) -> None:
    started_at = datetime(2026, 6, 11, 9, 0, tzinfo=UTC)
    recorder = FakeRecorder(tmp_path, is_recording=True)
    recorder.active_session = RecordingSession(
        meta=MeetingMeta(
            slug="2026-06-11_09-00_product-sync",
            started_at=started_at,
            calendar_title="Product Sync",
        ),
        wav_path=tmp_path / "recording.wav",
    )
    controller = TrayController(
        settings=_settings(tmp_path),
        recorder=recorder,
        pipeline=FakePipeline(),
        event_queue=queue.Queue(),
        now=lambda: datetime(2026, 6, 11, 9, 1, 5, tzinfo=UTC),
    )

    assert controller.recording_duration_seconds() == 65


def test_rumps_tray_app_renders_notifications(tmp_path: Path) -> None:
    fake_rumps = FakeRumps()
    controller = TrayController(
        settings=_settings(tmp_path),
        recorder=FakeRecorder(tmp_path),
        pipeline=FakePipeline(),
        event_queue=queue.Queue(),
    )
    app = RumpsTrayApp(controller, rumps_module=fake_rumps)
    meeting_time = datetime.now().astimezone() + timedelta(minutes=4)

    app.handle_event(NotifyEvent("Meeting transcribed", "Done"))
    app.handle_event(MeetingDetected("event", "Standup", meeting_time, "meet"))

    assert fake_rumps.notifications[0] == ("Meeting transcribed", "", "Done")
    assert fake_rumps.notifications[1][0] == "Meeting starting soon"
    assert "Standup starts in" in fake_rumps.notifications[1][2]


def test_rumps_tray_app_updates_recording_duration_label(tmp_path: Path) -> None:
    started_at = datetime(2026, 6, 11, 9, 0, tzinfo=UTC)
    current_time = datetime(2026, 6, 11, 9, 0, tzinfo=UTC)
    recorder = FakeRecorder(tmp_path, is_recording=True)
    recorder.active_session = RecordingSession(
        meta=MeetingMeta(
            slug="2026-06-11_09-00_product-sync",
            started_at=started_at,
            calendar_title="Product Sync",
        ),
        wav_path=tmp_path / "recording.wav",
    )
    controller = TrayController(
        settings=_settings(tmp_path),
        recorder=recorder,
        pipeline=FakePipeline(),
        event_queue=queue.Queue(),
        now=lambda: current_time,
    )
    app = RumpsTrayApp(controller, rumps_module=FakeRumps())

    current_time = datetime(2026, 6, 11, 9, 1, 5, tzinfo=UTC)
    app.drain_events()

    assert app.recording_item.title == "■ Stop Recording · 01:05"
    assert app.app.title == "01:05"


def test_rumps_tray_app_disables_default_quit_button(tmp_path: Path) -> None:
    fake_rumps = FakeRumps()
    controller = TrayController(
        settings=_settings(tmp_path),
        recorder=FakeRecorder(tmp_path),
        pipeline=FakePipeline(),
        event_queue=queue.Queue(),
    )

    app = RumpsTrayApp(controller, rumps_module=fake_rumps)

    assert app.app.quit_button is None
    assert app.app.title is None
    assert app.app.icon.endswith("robot-template.png")
    assert app.app.template is True
    titles = [item.title for item in app.app.menu.items if item is not None]
    configuration_titles = _submenu_titles(app, menu.CONFIGURATION_LABEL)
    debugging_titles = _submenu_titles(app, menu.DEBUGGING_LABEL)
    assert titles.count(menu.QUIT_LABEL) == 1
    assert titles.count(menu.CONFIGURATION_LABEL) == 1
    assert titles.count(menu.DEBUGGING_LABEL) == 1
    assert menu.AUDIO_MODE_HEADER not in titles
    assert configuration_titles == [
        menu.AUDIO_MODE_HEADER,
        "✓ Full Meeting",
        "Silent System Only",
        menu.KNOWN_SPEAKERS_LABEL,
        menu.NOTES_PROMPT_LABEL,
        menu.PREFERENCES_LABEL,
    ]
    assert debugging_titles == [
        menu.processing_header_label(0),
        menu.LEGACY_RECOVERY_SCAN_LABEL,
        menu.SYNC_LABEL,
        menu.RETRY_PROCESSING_LABEL,
        menu.RUN_DIAGNOSTICS_LABEL,
        menu.TEST_NOTIFICATION_LABEL,
    ]


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        b2_application_key_id="key-id",
        b2_application_key="secret",
        b2_endpoint="https://s3.example.com",
        b2_region="us-west-004",
        b2_bucket_name="bucket",
        assemblyai_api_key="assembly-key",
        meetings_dir=tmp_path / "meetings",
    )


def _submenu_titles(app: RumpsTrayApp, title: str) -> list[str]:
    submenu = next(item for item in app.app.menu.items if item and item.title == title)
    return [item.title for item in submenu.items if item is not None]


@dataclass
class FakeRecorder:
    tmp_path: Path
    capture_mode: str = "full-meeting"
    is_recording: bool = False
    started_title: str | None = None
    started_candidates: tuple[str, ...] = ()
    active_session: RecordingSession | None = None

    def __post_init__(self) -> None:
        audio_path = self.tmp_path / "recording.m4a"
        audio_path.write_bytes(b"audio")
        self.result = RecordingResult(
            meta=MeetingMeta(
                slug="2026-06-11_09-00_product-sync",
                started_at=datetime(2026, 6, 11, 9, 0, tzinfo=UTC),
                calendar_title="Product Sync",
                duration_minutes=5,
            ),
            audio_path=audio_path,
            wav_path=self.tmp_path / "recording.wav",
        )

    def start(
        self,
        calendar_title: str = "Untitled",
        *,
        speaker_candidates: tuple[str, ...] = (),
    ) -> RecordingSession:
        self.started_title = calendar_title
        self.started_candidates = speaker_candidates
        self.is_recording = True
        self.active_session = RecordingSession(
            meta=self.result.meta.with_speaker_candidates(speaker_candidates),
            wav_path=self.result.wav_path,
        )
        return self.active_session

    def stop(self):
        self.is_recording = False
        if self.active_session is not None:
            self.result = RecordingResult(
                meta=self.active_session.meta,
                audio_path=self.result.audio_path,
                wav_path=self.result.wav_path,
            )
        self.active_session = None
        return self.result


@dataclass
class FailingRecorder:
    message: str
    is_recording: bool = False
    active_session: RecordingSession | None = None

    def start(
        self,
        calendar_title: str = "Untitled",
        *,
        speaker_candidates: tuple[str, ...] = (),
    ) -> None:
        del calendar_title, speaker_candidates
        raise RuntimeError(self.message)

    def stop(self):
        raise RuntimeError(self.message)


class FakePipeline:
    def __init__(self):
        self.calls = []

    def run(self, audio_path: Path, meta: MeetingMeta) -> None:
        self.calls.append((audio_path, meta))


class ImmediateThread:
    def __init__(self, *, target, args=(), daemon=False):
        self.target = target
        self.args = args
        self.daemon = daemon
    def start(self) -> None:
        self.target(*self.args)

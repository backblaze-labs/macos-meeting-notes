"""Tests for tray controller and event rendering."""

from __future__ import annotations

import queue
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from meeting_memory.config.settings import Settings
from meeting_memory.service.recorder import RecordingResult
from meeting_memory.types.events import MeetingDetected, NotifyEvent
from meeting_memory.types.meeting import MeetingMeta
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
    assert pipeline.calls == [(recorder.result.audio_path, recorder.result.meta)]


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


def test_rumps_tray_app_renders_notifications(tmp_path: Path) -> None:
    fake_rumps = FakeRumps()
    controller = TrayController(
        settings=_settings(tmp_path),
        recorder=FakeRecorder(tmp_path),
        pipeline=FakePipeline(),
        event_queue=queue.Queue(),
    )
    app = RumpsTrayApp(controller, rumps_module=fake_rumps)
    meeting_time = datetime.now().astimezone() + _minutes(4)

    app.handle_event(NotifyEvent("Meeting transcribed", "Done"))
    app.handle_event(MeetingDetected("event", "Standup", meeting_time, "meet"))

    assert fake_rumps.notifications[0] == ("Meeting transcribed", "", "Done")
    assert fake_rumps.notifications[1][0] == "Meeting starting soon"
    assert "Standup starts in" in fake_rumps.notifications[1][2]


def _minutes(value: int):
    from datetime import timedelta

    return timedelta(minutes=value)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        b2_application_key_id="key-id",
        b2_application_key="secret",
        b2_endpoint="https://s3.example.com",
        b2_region="us-west-004",
        b2_bucket_name="bucket",
        assemblyai_api_key="assembly-key",
        meetings_dir=tmp_path / "meetings",
    )


@dataclass
class FakeRecorder:
    tmp_path: Path
    is_recording: bool = False
    started_title: str | None = None

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

    def start(self, calendar_title: str = "Untitled") -> None:
        self.started_title = calendar_title
        self.is_recording = True

    def stop(self):
        self.is_recording = False
        return self.result


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
        def __init__(self, name, title=None):
            self.name = name
            self.title = title
            self.menu = FakeMenu()

        def run(self) -> None:
            pass

    def notification(self, title, subtitle, message) -> None:
        self.notifications.append((title, subtitle, message))

    def quit_application(self, _sender=None) -> None:
        pass

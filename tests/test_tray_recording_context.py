"""Tests for tray calendar context and ad-hoc title prompting."""

from __future__ import annotations

import queue
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from meeting_memory.config.settings import Settings
from meeting_memory.service.recorder import RecordingResult, RecordingSession
from meeting_memory.types.events import NotifyEvent
from meeting_memory.types.meeting import MeetingMeta, RecordingContext, build_meeting_slug
from meeting_memory.ui.tray import RumpsTrayApp, TrayController


def test_tray_controller_reminds_to_stop_at_calendar_end(tmp_path: Path) -> None:
    now = datetime(2026, 6, 11, 9, 0, tzinfo=UTC)
    sleeps: list[float] = []
    controller = TrayController(
        settings=_settings(tmp_path),
        recorder=FakeRecorder(tmp_path),
        pipeline=FakePipeline(),
        event_queue=queue.Queue(),
        thread_factory=ImmediateThread,
        timer_thread_factory=PassiveThread,
        now=lambda: now,
        sleeper=lambda seconds: sleeps.append(seconds),
    )

    controller.start_recording("Product Sync", ends_at=now + timedelta(minutes=30))

    assert sleeps == [1800]
    assert controller.drain_events() == [
        NotifyEvent(
            title="Meeting ending",
            body="Product Sync is ending now. Stop recording?",
            action_label="Stop",
            action="stop_recording",
        )
    ]


def test_tray_controller_auto_stops_at_recording_limit(tmp_path: Path) -> None:
    sleeps: list[float] = []
    recorder = FakeRecorder(tmp_path)
    pipeline = FakePipeline()
    controller = TrayController(
        settings=_settings(tmp_path, max_recording_minutes=1),
        recorder=recorder,
        pipeline=pipeline,
        event_queue=queue.Queue(),
        thread_factory=ImmediateThread,
        timer_thread_factory=ImmediateThread,
        sleeper=lambda seconds: sleeps.append(seconds),
    )

    controller.start_recording("Long Meeting")

    assert sleeps == [60]
    assert recorder.is_recording is False
    assert pipeline.calls == [(recorder.result.audio_path, recorder.result.meta)]
    assert controller.drain_events()[0] == NotifyEvent(
        title="Recording limit reached",
        body="Long Meeting reached 1 min.",
    )


def test_rumps_tray_app_prompts_for_title_after_stop_without_calendar_context(
    tmp_path: Path,
) -> None:
    fake_rumps = FakeRumps(prompt_text="Ad hoc Recording")
    recorder = FakeRecorder(tmp_path)
    pipeline = FakePipeline()
    controller = TrayController(
        settings=_settings(tmp_path),
        recorder=recorder,
        pipeline=pipeline,
        event_queue=queue.Queue(),
        thread_factory=ImmediateThread,
    )
    app = RumpsTrayApp(controller, rumps_module=fake_rumps)

    app.toggle_recording()

    assert recorder.started_title == "Untitled"
    assert fake_rumps.window_requests == []

    app.toggle_recording()
    app.drain_events()

    assert fake_rumps.window_requests == ["Meeting Title"]
    assert pipeline.calls[0][1].calendar_title == "Ad hoc Recording"
    assert pipeline.calls[0][1].slug == "2026-06-11_09-00_ad-hoc-recording"


def test_rumps_tray_app_uses_calendar_context_without_prompt(tmp_path: Path) -> None:
    fake_rumps = FakeRumps(prompt_text="Should not use")
    ends_at = datetime(2026, 6, 11, 9, 30, tzinfo=UTC)
    recorder = FakeRecorder(tmp_path)
    controller = TrayController(
        settings=_settings(tmp_path),
        recorder=recorder,
        pipeline=FakePipeline(),
        event_queue=queue.Queue(),
        recording_context_provider=lambda: RecordingContext(
            "Calendar Sync",
            ends_at=ends_at,
            speaker_candidates=("Casey", "Drew"),
        ),
    )
    app = RumpsTrayApp(controller, rumps_module=fake_rumps)

    app.toggle_recording()

    assert recorder.started_title == "Calendar Sync"
    assert recorder.started_candidates == ("Casey", "Drew")
    assert fake_rumps.window_requests == []


def _settings(tmp_path: Path, *, max_recording_minutes: int = 180) -> Settings:
    return Settings(
        b2_application_key_id="key-id",
        b2_application_key="secret",
        b2_endpoint="https://s3.example.com",
        b2_region="us-west-004",
        b2_bucket_name="bucket",
        assemblyai_api_key="assembly-key",
        meetings_dir=tmp_path / "meetings",
        max_recording_minutes=max_recording_minutes,
    )


@dataclass
class FakeRecorder:
    tmp_path: Path
    is_recording: bool = False
    started_title: str | None = None
    started_candidates: tuple[str, ...] = ()
    active_session: RecordingSession | None = None

    def __post_init__(self) -> None:
        audio_path = self.tmp_path / "recording.m4a"
        audio_path.write_bytes(b"audio")
        started_at = datetime(2026, 6, 11, 9, 0, tzinfo=UTC)
        self.started_at = started_at
        self.result = self._result_for("Product Sync")

    def start(
        self,
        calendar_title: str = "Untitled",
        *,
        speaker_candidates: tuple[str, ...] = (),
    ) -> RecordingSession:
        self.started_title = calendar_title
        self.started_candidates = speaker_candidates
        self.is_recording = True
        self.result = self._result_for(calendar_title, speaker_candidates=speaker_candidates)
        self.active_session = RecordingSession(self.result.meta, self.result.wav_path)
        return self.active_session

    def stop(self):
        self.is_recording = False
        self.active_session = None
        return self.result

    def _result_for(
        self,
        title: str,
        *,
        speaker_candidates: tuple[str, ...] = (),
    ) -> RecordingResult:
        audio_path = self.tmp_path / "recording.m4a"
        return RecordingResult(
            meta=MeetingMeta(
                slug=build_meeting_slug(self.started_at, title),
                started_at=self.started_at,
                calendar_title=title,
                speaker_candidates=speaker_candidates,
            ),
            audio_path=audio_path,
            wav_path=self.tmp_path / "recording.wav",
        )


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


class PassiveThread:
    def __init__(self, *, target, args=(), daemon=False):
        self.target = target
        self.args = args
        self.daemon = daemon

    def start(self) -> None:
        pass


class FakeMenu:
    def __init__(self):
        self.items = []

    def clear(self) -> None:
        self.items.clear()

    def add(self, item) -> None:
        self.items.append(item)


class FakeRumps:
    def __init__(self, *, prompt_text: str = "Untitled", prompt_clicked: int = 1):
        self.prompt_text = prompt_text
        self.prompt_clicked = prompt_clicked
        self.window_requests = []

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

    def Window(self, *, message, title, default_text, ok, cancel):
        del message, default_text, ok, cancel
        self.window_requests.append(title)
        return FakeWindow(clicked=self.prompt_clicked, text=self.prompt_text)

    def notification(self, title, subtitle, message, **kwargs) -> None:
        pass

    def quit_application(self, _sender=None) -> None:
        pass


class FakeWindow:
    def __init__(self, *, clicked: int, text: str):
        self.clicked = clicked
        self.text = text

    def run(self):
        return self

"""Tests for non-blocking, single-flight tray recording transitions."""

from __future__ import annotations

import queue
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tray_fakes import FakeRumps

from meeting_memory.config.settings import Settings
from meeting_memory.service.recorder import RecordingResult, RecordingSession
from meeting_memory.types.events import NotifyEvent
from meeting_memory.types.meeting import MeetingMeta, RecordingContext
from meeting_memory.ui.controller import TrayController
from meeting_memory.ui.recording_transitions import RecordingTransitions
from meeting_memory.ui.tray import RumpsTrayApp


def test_tray_toggle_start_and_stop_are_non_blocking_and_single_flight(tmp_path: Path) -> None:
    recorder = BlockingRecorder(tmp_path)
    context_entered = threading.Event()
    context_release = threading.Event()

    def context_provider() -> RecordingContext:
        context_entered.set()
        if not context_release.wait(timeout=2):
            raise TimeoutError("test did not release context")
        return RecordingContext("Product Sync")

    pipeline = EventPipeline()
    controller = TrayController(
        settings=_settings(tmp_path),
        recorder=recorder,
        pipeline=pipeline,
        event_queue=queue.Queue(),
        recording_context_provider=context_provider,
        timer_thread_factory=PassiveThread,
    )
    app = RumpsTrayApp(controller, rumps_module=FakeRumps())

    assert _elapsed(app.toggle_recording) < 0.3
    assert context_entered.wait(timeout=1)
    assert _elapsed(app.toggle_recording) < 0.3
    assert recorder.start_calls == 0

    context_release.set()
    assert recorder.start_entered.wait(timeout=1)
    assert _elapsed(app.toggle_recording) < 0.3
    assert recorder.start_calls == 1
    recorder.start_release.set()
    assert recorder.started.wait(timeout=1)

    assert _elapsed(app.toggle_recording) < 0.3
    assert recorder.stop_entered.wait(timeout=1)
    assert _elapsed(app.toggle_recording) < 0.3
    assert recorder.stop_calls == 1
    recorder.stop_release.set()

    assert pipeline.called.wait(timeout=1)
    assert recorder.stop_calls == 1
    assert pipeline.calls == [(recorder.result.audio_path, recorder.result.meta)]
    assert NotifyEvent(
        "Recording saved",
        "Product Sync · processing queued",
        show_notification=False,
    ) in controller.drain_events()


@pytest.mark.parametrize("failure_stage", ["construct", "start"])
def test_transition_thread_launch_failure_notifies_and_resets(failure_stage: str) -> None:
    events: queue.Queue[object] = queue.Queue()
    started: list[str] = []
    transitions = RecordingTransitions(
        ImmediateRecorder(),
        events,
        context_provider=lambda: None,
        on_started=lambda title, _ends_at: started.append(title),
        on_stopped=lambda _result: None,
        thread_factory=FailOnceThreadFactory(failure_stage),
    )

    assert transitions.request_start("First") is False
    assert events.get_nowait() == NotifyEvent(
        "Recording could not start",
        f"thread {failure_stage} failed",
    )

    assert transitions.request_start("Second") is True
    assert started == ["Second"]


def test_transition_worker_error_notifies_and_resets() -> None:
    events: queue.Queue[object] = queue.Queue()
    recorder = FailOnceRecorder()
    started: list[str] = []
    transitions = RecordingTransitions(
        recorder,
        events,
        context_provider=lambda: None,
        on_started=lambda title, _ends_at: started.append(title),
        on_stopped=lambda _result: None,
        thread_factory=ImmediateThread,
    )

    assert transitions.request_start("First") is True
    assert events.get_nowait() == NotifyEvent("Recording could not start", "helper failed")

    assert transitions.request_start("Second") is True
    assert started == ["Second"]


def test_started_recording_is_stopped_safely_when_timer_setup_fails() -> None:
    events: queue.Queue[object] = queue.Queue()
    recorder = ImmediateRecorder()
    thread_calls = []

    def thread_factory(**kwargs):
        thread_calls.append(kwargs)
        return ImmediateThread(**kwargs)

    def fail_timer_setup(_title: str, _ends_at: datetime | None) -> None:
        raise RuntimeError("timer thread failed")

    transitions = RecordingTransitions(
        recorder,
        events,
        context_provider=lambda: None,
        on_started=fail_timer_setup,
        on_stopped=lambda _result: None,
        thread_factory=thread_factory,
    )

    assert transitions.request_start("First") is True
    assert recorder.stop_calls == 1
    assert len(thread_calls) == 1
    assert events.get_nowait() == NotifyEvent(
        "Recording setup failed",
        "timer thread failed. Stopping safely.",
    )
    assert events.empty()
def test_stop_requested_before_start_worker_resets_runs_once() -> None:
    recorder = ImmediateRecorder()
    callback_entered = threading.Event()
    callback_release = threading.Event()
    stopped: list[RecordingResult] = []

    def on_started(_title: str, _ends_at: datetime | None) -> None:
        callback_entered.set()
        assert callback_release.wait(timeout=2)

    transitions = RecordingTransitions(
        recorder,
        queue.Queue(),
        context_provider=lambda: None,
        on_started=on_started,
        on_stopped=stopped.append,
    )

    assert transitions.request_start("First") is True
    assert callback_entered.wait(timeout=1)
    assert transitions.request_stop() is True
    assert transitions.request_stop() is False
    callback_release.set()

    assert recorder.stopped.wait(timeout=1)
    assert recorder.stop_calls == 1
class BlockingRecorder:
    def __init__(self, tmp_path: Path) -> None:
        meta = MeetingMeta(
            slug="2026-06-11_09-00_product-sync",
            started_at=datetime(2026, 6, 11, 9, 0, tzinfo=UTC),
            calendar_title="Product Sync",
        )
        self.result = RecordingResult(meta, tmp_path / "recording.m4a", tmp_path / "recording.wav")
        self.is_recording = False
        self.active_session = None
        self.start_calls = 0
        self.stop_calls = 0
        self.start_entered = threading.Event()
        self.start_release = threading.Event()
        self.started = threading.Event()
        self.stop_entered = threading.Event()
        self.stop_release = threading.Event()

    def start(self, calendar_title: str, *, speaker_candidates=()) -> RecordingSession:
        del calendar_title, speaker_candidates
        self.start_calls += 1
        self.start_entered.set()
        if not self.start_release.wait(timeout=2):
            raise TimeoutError("test did not release start")
        self.is_recording = True
        self.active_session = RecordingSession(self.result.meta, self.result.wav_path)
        self.started.set()
        return self.active_session

    def stop(self) -> RecordingResult:
        self.stop_calls += 1
        self.stop_entered.set()
        if not self.stop_release.wait(timeout=2):
            raise TimeoutError("test did not release stop")
        self.is_recording = False
        self.active_session = None
        return self.result
class ImmediateRecorder:
    def __init__(self) -> None:
        meta = MeetingMeta("test", datetime.now(UTC), "Test")
        self.result = RecordingResult(meta, Path("test.m4a"), Path("test.wav"))
        self.stop_calls = 0
        self.stopped = threading.Event()

    def start(self, calendar_title: str, *, speaker_candidates=()) -> object:
        del calendar_title, speaker_candidates
        return object()

    def stop(self) -> RecordingResult:
        self.stop_calls += 1
        self.stopped.set()
        return self.result
class FailOnceRecorder(ImmediateRecorder):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def start(self, calendar_title: str, *, speaker_candidates=()) -> object:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("helper failed")
        return super().start(calendar_title, speaker_candidates=speaker_candidates)
class EventPipeline:
    summarizer_client = None

    def __init__(self) -> None:
        self.calls = []
        self.called = threading.Event()

    def run(self, audio_path: Path, meta: MeetingMeta) -> None:
        self.calls.append((audio_path, meta))
        self.called.set()
class ImmediateThread:
    def __init__(self, *, target, args=(), daemon=False) -> None:
        self.target = target
        self.args = args
        self.daemon = daemon

    def start(self) -> None:
        self.target(*self.args)


class PassiveThread(ImmediateThread):
    def start(self) -> None:
        pass


class FailingStartThread(ImmediateThread):
    def __init__(self, *, message: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.message = message

    def start(self) -> None:
        raise RuntimeError(self.message)


class FailOnceThreadFactory:
    def __init__(self, failure_stage: str) -> None:
        self.failure_stage = failure_stage
        self.calls = 0

    def __call__(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            if self.failure_stage == "construct":
                raise RuntimeError("thread construct failed")
            return FailingStartThread(message="thread start failed", **kwargs)
        return ImmediateThread(**kwargs)


def _elapsed(callback) -> float:
    started_at = time.monotonic()
    callback()
    return time.monotonic() - started_at


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

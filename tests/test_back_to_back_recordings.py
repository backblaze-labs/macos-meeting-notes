"""A pending transcript must never block the next recording."""

from __future__ import annotations

import queue
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from meeting_memory.service.meeting_store import MeetingStore
from meeting_memory.service.recorder import RecordingResult, RecordingSession
from meeting_memory.service.runtime_jobs import RuntimeJobs
from meeting_memory.types.meeting import MeetingMeta, PostCommitPolicy
from meeting_memory.ui.controller import TrayController


class DeferredThread:
    created: list[DeferredThread] = []

    def __init__(self, target, args=(), **_kwargs) -> None:
        self.target = target
        self.args = args
        self.__class__.created.append(self)

    def start(self) -> None:
        pass


class UnusedTranscriptionClient:
    def submit(self, _audio):
        raise AssertionError("deferred worker should not run")

    def resume(self, _job_id):
        raise AssertionError("deferred worker should not run")


def _committed_meeting(root: Path, minute: int):
    source = root / f"source-{minute}.m4a"
    source.write_bytes(b"audio")
    meta = MeetingMeta(
        f"2026-08-20_09-{minute:02d}_sync",
        datetime(2026, 8, 20, 9, minute, tzinfo=UTC),
        "Sync",
    )
    return MeetingStore(root / "meetings").commit(
        source,
        meta,
        PostCommitPolicy(transcription=True),
    )


def test_transcription_single_flight_is_scoped_per_meeting(tmp_path: Path) -> None:
    DeferredThread.created = []
    first = _committed_meeting(tmp_path, 0)
    second = _committed_meeting(tmp_path, 1)
    jobs = RuntimeJobs(
        first.directory.parent,
        lambda _event: None,
        transcription_client=UnusedTranscriptionClient(),
        thread_factory=DeferredThread,
    )

    jobs.launch_for_commit(first, transcription=True, backup=False)
    jobs.launch_for_commit(second, transcription=True, backup=False)

    assert len(DeferredThread.created) == 2


class ImmediateRecorder:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.is_recording = False
        self.active_session = None
        self.start_count = 0
        self.started = threading.Event()

    def start(self, calendar_title: str, *, speaker_candidates=()) -> RecordingSession:
        del speaker_candidates
        self.start_count += 1
        started_at = datetime(2026, 8, 20, 9, tzinfo=UTC) + timedelta(minutes=self.start_count)
        meta = MeetingMeta(f"meeting-{self.start_count}", started_at, calendar_title)
        path = self.root / f"recording-{self.start_count}.wav"
        self.active_session = RecordingSession(meta, path)
        self.is_recording = True
        self.started.set()
        return self.active_session

    def stop(self) -> RecordingResult:
        assert self.active_session is not None
        session = self.active_session
        self.is_recording = False
        self.active_session = None
        return RecordingResult(session.meta, session.wav_path, session.wav_path)


class BlockingTranscriptionPipeline:
    summarizer_client = None

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def run(self, _audio_path: Path, _meta: MeetingMeta) -> None:
        self.entered.set()
        assert self.release.wait(timeout=3)


class PassiveThread:
    def __init__(self, **_kwargs) -> None:
        pass

    def start(self) -> None:
        pass


def test_next_recording_starts_while_previous_transcript_is_pending(tmp_path: Path) -> None:
    recorder = ImmediateRecorder(tmp_path)
    pipeline = BlockingTranscriptionPipeline()
    controller = TrayController(
        settings=SimpleNamespace(max_recording_minutes=240),
        recorder=recorder,
        pipeline=pipeline,
        event_queue=queue.Queue(),
        timer_thread_factory=PassiveThread,
    )

    controller.start_recording("First")
    assert _wait_for(lambda: recorder.start_count == 1)
    controller.stop_recording()
    assert pipeline.entered.wait(timeout=2)
    assert _wait_for(lambda: controller._transitions._active is None)

    recorder.started.clear()
    controller.start_recording("Second")

    assert recorder.started.wait(timeout=2)
    assert recorder.start_count == 2
    assert pipeline.release.is_set() is False
    pipeline.release.set()


def _wait_for(condition) -> bool:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False

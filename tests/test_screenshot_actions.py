"""Tests for tray screenshot capture and post-commit attachment."""

from __future__ import annotations

import queue
from datetime import UTC, datetime, timedelta
from pathlib import Path

from test_tray import FakePipeline, FakeRecorder, _settings
from tray_fakes import FakeRumps

from meeting_memory.service.recorder import RecordingSession
from meeting_memory.service.screenshots import ScreenshotStore
from meeting_memory.types.events import NotifyEvent, RecordingCommitted, TranscriptReady
from meeting_memory.types.meeting import MeetingMeta, MeetingRef
from meeting_memory.ui.screenshot_actions import (
    CAPTURE_FAILED_TITLE,
    NO_RECORDING_TITLE,
    SAVED_TITLE,
    ScreenshotActions,
)
from meeting_memory.ui.tray import RumpsTrayApp, TrayController

STARTED_AT = datetime(2026, 6, 11, 9, 0, tzinfo=UTC)
SLUG = "2026-06-11_09-00_product-sync"


def test_take_requires_an_active_recording(tmp_path: Path) -> None:
    controller, store = _controller(tmp_path)
    actions = ScreenshotActions(controller, store)

    actions.take()

    assert controller.drain_events() == [
        NotifyEvent(NO_RECORDING_TITLE, "Start a recording to capture screenshots for it.")
    ]
    assert not store.pending_root.exists()


def test_take_stages_a_screenshot_for_the_active_recording(tmp_path: Path) -> None:
    controller, store = _controller(tmp_path, recording=True)
    actions = ScreenshotActions(controller, store)

    actions.take()
    actions.take()

    assert controller.drain_events() == [
        NotifyEvent(SAVED_TITLE, "Screenshot 1 · Product Sync"),
        NotifyEvent(SAVED_TITLE, "Screenshot 2 · Product Sync"),
    ]
    assert sorted(path.name for path in (store.pending_root / "2026-06-11_09-00").iterdir()) == [
        "screenshot-01-at-01m05s.png",
        "screenshot-02-at-01m05s.png",
    ]


def test_take_reports_capture_failures(tmp_path: Path) -> None:
    def failing(_path: Path) -> None:
        raise RuntimeError("screencapture exited with 1")

    controller, _store = _controller(tmp_path, recording=True)
    store = ScreenshotStore(controller.settings.meetings_dir_path, capturer=failing)

    ScreenshotActions(controller, store).take()

    assert [event.title for event in controller.drain_events()] == [CAPTURE_FAILED_TITLE]


def test_committed_meeting_receives_its_staged_screenshots(tmp_path: Path) -> None:
    controller, store = _controller(tmp_path, recording=True)
    actions = ScreenshotActions(controller, store)
    actions.take()
    meeting = _publish(controller.settings.meetings_dir_path, SLUG)

    assert actions.handle_event(TranscriptReady(meeting)) == ()
    attached = actions.handle_event(RecordingCommitted(meeting))

    assert attached == (meeting.directory / "screenshot-01-at-01m05s.png",)


def test_tray_take_screenshot_stages_and_commit_attaches(tmp_path: Path) -> None:
    controller, store = _controller(tmp_path, recording=True)
    fake_rumps = FakeRumps()
    app = RumpsTrayApp(controller, rumps_module=fake_rumps, screenshot_store=store)

    app.take_screenshot()
    app.take_screenshot()
    meeting = _publish(controller.settings.meetings_dir_path, SLUG)
    app.handle_event(RecordingCommitted(meeting))

    assert app.screenshot_hotkey is None
    assert sorted(path.name for path in (meeting.directory / "screenshots").iterdir()) == [
        "screenshot-01-at-01m05s.png",
        "screenshot-02-at-01m05s.png",
    ]
    assert fake_rumps.notifications[0][0] == "Recording saved"


def _controller(
    tmp_path: Path, *, recording: bool = False
) -> tuple[TrayController, ScreenshotStore]:
    recorder = FakeRecorder(tmp_path, is_recording=recording)
    if recording:
        recorder.active_session = RecordingSession(
            meta=MeetingMeta(slug=SLUG, started_at=STARTED_AT, calendar_title="Product Sync"),
            wav_path=tmp_path / "recording.wav",
        )
    controller = TrayController(
        settings=_settings(tmp_path),
        recorder=recorder,
        pipeline=FakePipeline(),
        event_queue=queue.Queue(),
        now=lambda: STARTED_AT + timedelta(seconds=65),
    )
    store = ScreenshotStore(
        controller.settings.meetings_dir_path, capturer=lambda path: path.write_bytes(b"png")
    )
    return controller, store


def _publish(meetings_dir: Path, slug: str) -> MeetingRef:
    directory = meetings_dir / slug
    directory.mkdir(parents=True)
    (directory / "transcript.md").write_text("---\nschema_version: 2\n---\n")
    (directory / "recording.m4a").write_bytes(b"audio")
    return MeetingRef(slug, "Product Sync", directory)

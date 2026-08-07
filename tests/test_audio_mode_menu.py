"""Tests for native audio mode tray actions."""

from __future__ import annotations

import queue

from tray_fakes import FakeMenu, FakeRumps

from meeting_memory.config.settings import Settings
from meeting_memory.service.audio_modes import SILENT_SYSTEM_ONLY
from meeting_memory.types.events import NotifyEvent
from meeting_memory.ui.audio_modes import AudioModeMenu


def test_audio_mode_menu_applies_mode_and_rebuilds(tmp_path) -> None:
    event_queue: queue.Queue[object] = queue.Queue()
    recorder = FakeRecorder()
    controller = FakeController(_settings(tmp_path), recorder, event_queue)
    rebuilds = 0

    def rebuild_menu() -> None:
        nonlocal rebuilds
        rebuilds += 1

    menu = AudioModeMenu(
        FakeRumps(),
        controller,
        rebuild_menu=rebuild_menu,
        applier=lambda mode, item: setattr(item, "capture_mode", mode.key),
    )

    menu.select_mode(SILENT_SYSTEM_ONLY)

    assert recorder.capture_mode == "silent-system-only"
    assert rebuilds == 1
    assert event_queue.get_nowait() == NotifyEvent(
        "Audio mode changed",
        (
            "Silent System Only: record system audio with microphone off "
            "and playback muted."
        ),
    )


def test_audio_mode_menu_renders_active_mode(tmp_path) -> None:
    fake_menu = FakeMenu()
    mode_menu = AudioModeMenu(
        FakeRumps(),
        FakeController(_settings(tmp_path), FakeRecorder(), queue.Queue()),
        rebuild_menu=lambda: None,
    )

    mode_menu.add_items(fake_menu)

    titles = [item.title for item in fake_menu.items if item is not None]
    assert titles == ["Audio Mode", "✓ Full Meeting", "Silent System Only"]


class FakeController:
    def __init__(self, settings, recorder, event_queue):
        self.settings = settings
        self.recorder = recorder
        self.event_queue = event_queue


class FakeRecorder:
    capture_mode = "full-meeting"
    is_recording = False


def _settings(tmp_path) -> Settings:
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

"""View-model snapshot tests.

The snapshot covers every label the status-item menu and the compact
sidebar render, in menu order — the same rows the original dropdown showed,
including Pending Meeting Tasks. If the expected lists ever need
editing, the menu's content changed and the diff needs review — not a new
snapshot. Per-row unit tests for `build_view_model` live in
tests/test_sidebar_view_model_rows.py.
"""

from __future__ import annotations

import queue
from datetime import UTC, datetime
from pathlib import Path

from sidebar_view_model_test_fixtures import (
    flatten_view_model,
    readiness_report,
    recent_meeting,
    recovery_entry,
)
from test_tray import FakePipeline, FakeRecorder, _settings
from tray_fakes import FakeRumps

from meeting_memory.types.processing import ProcessingTask
from meeting_memory.ui.tray import RumpsTrayApp, TrayController

CONFIGURATION_TITLES = [
    "Configuration",
    "Audio Mode",
    "✓ Full Meeting",
    "Silent System Only",
    "Recording Core...",
    "Transcription...",
    "Backup...",
    "Calendar...",
    "Notes...",
    "Notes Customization...",
    "Authorize Google Calendar...",
    "Import Legacy Configuration...",
]
DIAGNOSTIC_TITLES = [
    "Find Legacy Recordings...",
    "Retry Pending B2 Backups",
    "Retry Failed Transcriptions",
    "Check Setup & Dependencies",
    "Test macOS Notifications",
]


def _build_populated_app(tmp_path: Path) -> RumpsTrayApp:
    recorder = FakeRecorder(tmp_path, is_recording=True)
    recorder.recording_warning = "clipping detected"
    controller = TrayController(
        settings=_settings(tmp_path),
        recorder=recorder,
        pipeline=FakePipeline(),
        event_queue=queue.Queue(),
        now=lambda: datetime(2026, 6, 15, 9, 1, 5, tzinfo=UTC),
    )
    controller.recent_meetings = lambda: [
        recent_meeting(tmp_path, 1, "Standup"),
        recent_meeting(tmp_path, 2, "Product Sync"),
        recent_meeting(tmp_path, 3, "1:1"),
    ]
    controller.recovered_recordings = lambda: [recovery_entry(tmp_path, 1)]

    app = RumpsTrayApp(
        controller,
        readiness_report=readiness_report(),
        rumps_module=FakeRumps(),
    )
    app.refresh_sidebar()
    return app


EXPECTED_POPULATED_TITLES = [
    "⚠︎ ■ Stop Recording · 00:00",
    "Recent Meetings",
    "2026-06-11 09:00 · Standup",
    "2026-06-12 09:00 · Product Sync",
    "2026-06-13 09:00 · 1:1",
    "Open Meetings Folder",
    *CONFIGURATION_TITLES,
    "Debugging",
    "Pending Meeting Tasks (0)",
    "Recording Core: Ready",
    "Transcription: Degraded",
    "Backup: Failed",
    "Calendar: Checking",
    "Notes: Unconfigured",
    "Interrupted Recordings (1)",
    "Recover 2026-06-11_09-00_meeting-1",
    *DIAGNOSTIC_TITLES,
    "Quit",
]


def test_sidebar_snapshot_populated(tmp_path: Path) -> None:
    app = _build_populated_app(tmp_path)
    assert flatten_view_model(app.view_model) == EXPECTED_POPULATED_TITLES


def test_sidebar_snapshot_idle_empty(tmp_path: Path) -> None:
    controller = TrayController(
        settings=_settings(tmp_path),
        recorder=FakeRecorder(tmp_path),
        pipeline=FakePipeline(),
        event_queue=queue.Queue(),
    )
    app = RumpsTrayApp(controller, rumps_module=FakeRumps())
    app.refresh_sidebar()
    assert flatten_view_model(app.view_model) == [
        "▶ Start Recording",
        "Recent Meetings",
        "No meetings yet",
        "Open Meetings Folder",
        *CONFIGURATION_TITLES,
        "Debugging",
        "Pending Meeting Tasks (0)",
        *DIAGNOSTIC_TITLES,
        "Quit",
    ]


def test_pending_speaker_review_shows_as_a_debugging_task(tmp_path: Path) -> None:
    # Manual speaker review is the default flow, so a diarized transcript that
    # is not yet confirmed appears under Pending Meeting Tasks.
    app = _build_populated_app(tmp_path)
    meeting = recent_meeting(tmp_path, 1, "Standup")
    app.controller.pending_processing_tasks = lambda: [
        ProcessingTask(meeting, "speaker_review", "review_speakers", "waiting", "Review speakers")
    ]
    app.refresh_sidebar()
    labels = flatten_view_model(app.view_model)
    assert "Pending Meeting Tasks (1)" in labels
    assert "2026-06-11 09:00 · Review speakers · Standup" in labels


def test_kept_label_meetings_offer_a_speaker_correction(tmp_path: Path) -> None:
    # Automatic Notes keep the diarized labels; the user can still map names.
    app = _build_populated_app(tmp_path)
    meeting = recent_meeting(tmp_path, 2, "Product Sync")
    app.controller.correctable_speaker_reviews = lambda: [
        ProcessingTask(meeting, "speaker_review", "review_speakers", "waiting", "Correct speakers")
    ]
    app.refresh_sidebar()
    labels = flatten_view_model(app.view_model)
    assert "Correct Speakers (1)" in labels
    assert "2026-06-12 09:00 · Correct speakers · Product Sync" in labels

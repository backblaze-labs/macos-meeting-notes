"""Sidebar view-model snapshot tests — see
docs/features/sidebar/completed/04-render-seam.md and
docs/features/sidebar/completed/07-cutover.md.

Plan 04 wrote this against the unmodified `rebuild_menu()` as the proof that
the render seam changed nothing. Plan 07 retired the menu, so the snapshot
now covers the `SidebarViewModel` the panel renders, in the vertical panel's
order — the same labels the dropdown showed, so nothing was lost in the
cutover. If the expected lists ever need editing, the sidebar's content
changed and the diff needs review — not a new snapshot.

Per-row/section unit tests for `build_view_model` itself live in
tests/test_sidebar_view_model_rows.py (split out to stay under the
300-line cap test_structure.py enforces on everything else).
"""

from __future__ import annotations

import queue
from datetime import UTC, datetime
from pathlib import Path

from sidebar_view_model_test_fixtures import (
    flatten_view_model,
    processing_task,
    readiness_report,
    recent_meeting,
    recovery_entry,
)
from test_tray import FakePipeline, FakeRecorder, _settings
from tray_fakes import FakeRumps

from meeting_memory.ui.tray import RumpsTrayApp, TrayController


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
    controller.pending_processing_tasks = lambda: [
        processing_task(tmp_path, 1, status="waiting"),
        processing_task(tmp_path, 2, status="failed"),
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
    "Audio Mode",
    "✓ Full Meeting",
    "Silent System Only",
    "Recent Meetings",
    "2026-06-11 09:00 · Standup",
    "2026-06-12 09:00 · Product Sync",
    "2026-06-13 09:00 · 1:1",
    "Open Meetings Folder",
    "Pending Meeting Tasks (2)",
    "2026-06-11 09:00 · Generate notes · Pending 1",
    "2026-06-12 09:00 · Generate notes · Pending 2",
    "Interrupted Recordings (1)",
    "Recover 2026-06-11_09-00_meeting-1",
    "Configuration",
    "Recording Core...",
    "Transcription...",
    "Backup...",
    "Calendar...",
    "Notes...",
    "Notes Customization...",
    "Authorize Google Calendar...",
    "Import Legacy Configuration...",
    "Diagnostics",
    "Find Legacy Recordings...",
    "Retry Pending B2 Backups",
    "Retry Failed Transcriptions",
    "Recording Core: Ready",
    "Transcription: Degraded",
    "Backup: Failed",
    "Calendar: Checking",
    "Notes: Unconfigured",
    "Check Setup & Dependencies",
    "Test macOS Notifications",
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
        "Audio Mode",
        "✓ Full Meeting",
        "Silent System Only",
        "Recent Meetings",
        "No meetings yet",
        "Open Meetings Folder",
        "Pending Meeting Tasks (0)",
        "Configuration",
        "Recording Core...",
        "Transcription...",
        "Backup...",
        "Calendar...",
        "Notes...",
        "Notes Customization...",
        "Authorize Google Calendar...",
        "Import Legacy Configuration...",
        "Diagnostics",
        "Find Legacy Recordings...",
        "Retry Pending B2 Backups",
        "Retry Failed Transcriptions",
        "Check Setup & Dependencies",
        "Test macOS Notifications",
        "Quit",
    ]

"""Shared fixtures for sidebar_view_model tests — see
docs/features/sidebar/completed/04-render-seam.md.

Split out of test_sidebar_view_model.py to keep both it and
test_sidebar_view_model_rows.py under the 300-line cap test_structure.py
enforces on everything else. Not named sidebar_view_model_fixtures.py:
that name is already taken by plan 05's SidebarViewModel test fixtures.
"""

from __future__ import annotations

import queue
from datetime import UTC, datetime
from pathlib import Path

from test_tray import FakePipeline, FakeRecorder, _settings
from tray_fakes import FakeRumps

from meeting_memory.types.capabilities import (
    Capability,
    CapabilityState,
    CapabilityStatus,
    ReadinessReport,
)
from meeting_memory.types.meeting import RecentMeeting
from meeting_memory.types.recovery import RecoveryIndexEntry, RecoveryOrigin
from meeting_memory.ui import menu
from meeting_memory.ui.audio_modes import AudioModeMenu
from meeting_memory.ui.sidebar_view_model import (
    ConfigurationActions,
    DebuggingActions,
    build_view_model,
)
from meeting_memory.ui.tray import TrayController


def flatten_view_model(view) -> list[str]:
    """Every label the status-item menu and sidebar render, in menu order —
    the successor of the dropdown-title snapshot, so nothing the old menu
    showed is lost by accident."""

    labels = [view.recording.label]
    labels.append(view.recent.title)
    labels += [row.label for row in view.recent.rows] or [view.recent.empty_label]
    labels.append(view.open_meetings_folder.label)
    labels.append(menu.CONFIGURATION_LABEL)
    labels.append(menu.AUDIO_MODE_HEADER)
    labels += [row.label for row in view.audio_modes]
    labels += [row.label for row in view.configuration]
    labels.append(menu.DEBUGGING_LABEL)
    labels.append(view.processing.title)
    labels += [row.label for row in view.processing.rows]
    labels += [row.label for row in view.readiness]
    if view.recovered.rows:
        labels.append(view.recovered.title)
        labels += [row.label for row in view.recovered.rows]
    labels += [row.label for row in view.diagnostics]
    labels.append(view.quit.label)
    return labels


def recent_meeting(tmp_path: Path, n: int, title: str) -> RecentMeeting:
    directory = tmp_path / f"meeting-{n}"
    return RecentMeeting(
        slug=f"2026-06-1{n}_09-00_meeting-{n}",
        calendar_title=title,
        started_at=datetime(2026, 6, 10 + n, 9, 0, tzinfo=UTC),
        directory=directory,
        markdown_path=directory / "notes.md",
    )


def recovery_entry(tmp_path: Path, n: int) -> RecoveryIndexEntry:
    session_dir = tmp_path / f"recovery-{n}"
    meeting = recent_meeting(tmp_path, n, f"Recovered {n}")
    return RecoveryIndexEntry(
        session_directory=session_dir,
        source_path=session_dir / "recording.wav",
        index_path=None,
        meta=meeting,  # RecentMeeting duck-types enough of MeetingMeta for .slug/.started_at
        origin=RecoveryOrigin.APP_STAGING,
        session_device=1,
        session_inode=1,
    )


def readiness_report() -> ReadinessReport:
    states = [
        CapabilityState.READY,
        CapabilityState.DEGRADED,
        CapabilityState.FAILED,
        CapabilityState.CHECKING,
        CapabilityState.UNCONFIGURED,
    ]
    return ReadinessReport(
        tuple(
            CapabilityStatus(
                capability,
                state,
                f"{capability.label} summary.",
                f"Configure {capability.label}." if state is not CapabilityState.READY else None,
            )
            for capability, state in zip(Capability, states, strict=True)
        )
    )


def controller(tmp_path: Path, **overrides) -> TrayController:
    return TrayController(
        settings=_settings(tmp_path),
        recorder=overrides.pop("recorder", FakeRecorder(tmp_path)),
        pipeline=FakePipeline(),
        event_queue=queue.Queue(),
        **overrides,
    )


def no_op_actions() -> tuple[ConfigurationActions, DebuggingActions]:
    return (
        ConfigurationActions(
            open_capability=lambda _capability: None,
            import_legacy=lambda: None,
            authorize_calendar=lambda: None,
            open_notes_prompt=lambda: None,
        ),
        DebuggingActions(
            review_speakers=lambda _path: None,
            generate_notes=lambda _path: None,
            process_recovered_recording=lambda _recording: None,
            scan_legacy_recoveries=lambda: None,
            sync_to_b2=lambda: None,
            retry_failed_processing=lambda: None,
            run_diagnostics=lambda _sender=None: None,
            send_test_notification=lambda _sender=None: None,
        ),
    )


def build(controller_: TrayController, *, readiness_report_=None) -> object:
    configuration_actions, debugging_actions = no_op_actions()
    audio_mode_menu = AudioModeMenu(FakeRumps(), controller_, on_change=lambda: None)
    return build_view_model(
        controller_,
        readiness_report=readiness_report_,
        audio_mode_menu=audio_mode_menu,
        configuration_actions=configuration_actions,
        debugging_actions=debugging_actions,
    )

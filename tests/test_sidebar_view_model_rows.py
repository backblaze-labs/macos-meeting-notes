"""Per-row/section unit tests for `build_view_model` — see
docs/features/sidebar/completed/04-render-seam.md.

The snapshot tests proving no rendered-menu regression live in
test_sidebar_view_model.py; this file is split out to stay under the
300-line cap test_structure.py enforces on everything else.
"""

from __future__ import annotations

from pathlib import Path

from sidebar_view_model_test_fixtures import (
    build,
    controller,
    no_op_actions,
    recent_meeting,
    recovery_entry,
)
from test_tray import FakeRecorder
from tray_fakes import FakeRumps

from meeting_memory.ui import menu
from meeting_memory.ui.audio_modes import AudioModeMenu
from meeting_memory.ui.sidebar_view_model import DebuggingActions, build_view_model


def test_recording_view_idle(tmp_path: Path) -> None:
    view = build(controller(tmp_path))
    assert view.recording.is_recording is False
    assert view.recording.audio_warning is False
    assert view.recording.label == menu.recording_label(is_recording=False)


def test_recording_view_recording_with_warning(tmp_path: Path) -> None:
    recorder = FakeRecorder(tmp_path, is_recording=True)
    recorder.recording_warning = "clipping"
    view = build(controller(tmp_path, recorder=recorder))
    assert view.recording.is_recording is True
    assert view.recording.audio_warning is True
    assert view.recording.label == menu.recording_label(
        is_recording=True, duration_seconds=view.recording.duration_seconds, audio_warning=True
    )


def test_recent_section_empty(tmp_path: Path) -> None:
    ctrl = controller(tmp_path)
    ctrl.recent_meetings = lambda: []
    view = build(ctrl)
    assert view.recent.rows == ()
    assert view.recent.empty_label == menu.NO_MEETINGS_LABEL


def test_recent_section_capped_at_three(tmp_path: Path) -> None:
    ctrl = controller(tmp_path)
    ctrl.recent_meetings = lambda: [
        recent_meeting(tmp_path, n, f"Meeting {n}") for n in range(1, 6)
    ]
    view = build(ctrl)
    assert len(view.recent.rows) == 3
    assert view.recent.empty_label is None


def test_recovered_section_marked_hidden_when_empty(tmp_path: Path) -> None:
    ctrl = controller(tmp_path)
    ctrl.recovered_recordings = lambda: []
    view = build(ctrl)
    assert view.recovered.rows == ()


def test_readiness_none_is_empty_tuple_not_a_crash(tmp_path: Path) -> None:
    view = build(controller(tmp_path), readiness_report_=None)
    assert view.readiness == ()


def test_recent_row_action_invokes_controller_open_meeting(tmp_path: Path) -> None:
    ctrl = controller(tmp_path)
    meeting = recent_meeting(tmp_path, 1, "Standup")
    ctrl.recent_meetings = lambda: [meeting]
    opened = []
    ctrl.open_meeting = lambda item: opened.append(item)
    view = build(ctrl)
    view.recent.rows[0].action()
    assert opened == [meeting]


def test_recovered_row_action_invokes_process_recovered_recording(tmp_path: Path) -> None:
    ctrl = controller(tmp_path)
    entry = recovery_entry(tmp_path, 1)
    ctrl.recovered_recordings = lambda: [entry]
    audio_mode_menu = AudioModeMenu(FakeRumps(), ctrl, on_change=lambda: None)
    configuration_actions, _ = no_op_actions()
    processed = []
    debugging_actions = DebuggingActions(
        review_speakers=lambda _path: None,
        generate_notes=lambda _path: None,
        process_recovered_recording=lambda recording: processed.append(recording),
        scan_legacy_recoveries=lambda: None,
        sync_to_b2=lambda: None,
        retry_failed_processing=lambda: None,
        run_diagnostics=lambda _sender=None: None,
        send_test_notification=lambda _sender=None: None,
    )
    view = build_view_model(
        ctrl,
        readiness_report=None,
        audio_mode_menu=audio_mode_menu,
        configuration_actions=configuration_actions,
        debugging_actions=debugging_actions,
    )
    view.recovered.rows[0].action()
    assert processed == [entry]


def test_open_meetings_folder_row_action_invokes_controller(tmp_path: Path) -> None:
    ctrl = controller(tmp_path)
    calls = []
    ctrl.open_meetings_folder = lambda: calls.append("opened")
    view = build(ctrl)
    view.open_meetings_folder.action()
    assert calls == ["opened"]

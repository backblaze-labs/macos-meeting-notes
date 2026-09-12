"""State -> view snapshot shared by the status-item menu and the sidebar.

`ui/tray.py:refresh_sidebar` builds one immutable `SidebarViewModel` after
every state change. The compact sidebar renders only `recording` (plus its
own fixed screenshot and quit buttons); `ui/status_menu.py` renders the rest
as the menu behind a right-click on the menu bar icon.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from meeting_memory.service.audio_modes import AUDIO_MODES
from meeting_memory.types.capabilities import Capability, ReadinessReport
from meeting_memory.ui import menu
from meeting_memory.ui.audio_modes import AudioModeMenu
from meeting_memory.ui.controller import TrayController
from meeting_memory.ui.processing_actions import run_processing_task
from meeting_memory.ui.setup_readiness import readiness_menu_label, readiness_tooltip

RECENT_MEETINGS_CAP = 3
RECOVERED_ROW_TOOLTIP = "Recover this recording and resume transcription."
B2_SYNC_TOOLTIP = "Upload meetings whose B2 backup is pending or failed."
TRANSCRIPTION_RETRY_TOOLTIP = "Re-run AssemblyAI transcription using the saved local audio."
DIAGNOSTICS_TOOLTIP = (
    "Check all five capabilities without making optional services block recording."
)
TEST_NOTIFICATION_TOOLTIP = "Send a local notification to verify macOS notification permissions."


@dataclass(frozen=True)
class ConfigurationActions:
    open_capability: Callable[[Capability], None]
    import_legacy: Callable[[], None]
    authorize_calendar: Callable[[], None]
    open_notes_prompt: Callable[[], None]


@dataclass(frozen=True)
class DebuggingActions:
    review_speakers: Callable[[Path], None]
    generate_notes: Callable[[Path], None]
    process_recovered_recording: Callable[[Any], None]
    scan_legacy_recoveries: Callable[[], None]
    sync_to_b2: Callable[[], None]
    retry_failed_processing: Callable[[], None]
    run_diagnostics: Callable[..., None]
    send_test_notification: Callable[..., None]


@dataclass(frozen=True, slots=True)
class RecordingView:
    is_recording: bool
    duration_seconds: int
    audio_warning: bool
    label: str


@dataclass(frozen=True, slots=True)
class RowView:
    label: str
    tooltip: str | None = None
    enabled: bool = True
    action: Callable[[], None] | None = None


@dataclass(frozen=True, slots=True)
class SectionView:
    title: str
    rows: tuple[RowView, ...]
    empty_label: str | None = None


@dataclass(frozen=True, slots=True)
class SidebarViewModel:
    recording: RecordingView
    audio_modes: tuple[RowView, ...]
    recent: SectionView
    processing: SectionView  # Pending Meeting Tasks; header always shown with its count
    recovered: SectionView  # rows empty -> section hidden
    readiness: tuple[RowView, ...]
    configuration: tuple[RowView, ...]
    diagnostics: tuple[RowView, ...]
    open_meetings_folder: RowView
    quit: RowView


def build_view_model(
    controller: TrayController,
    *,
    readiness_report: ReadinessReport | None,
    audio_mode_menu: AudioModeMenu,
    configuration_actions: ConfigurationActions,
    debugging_actions: DebuggingActions,
) -> SidebarViewModel:
    return SidebarViewModel(
        recording=recording_view_for(controller),
        audio_modes=_audio_mode_rows(audio_mode_menu),
        recent=_recent_section(controller),
        processing=_processing_section(controller, debugging_actions),
        recovered=_recovered_section(controller, debugging_actions),
        readiness=_readiness_rows(readiness_report),
        configuration=_configuration_rows(configuration_actions),
        diagnostics=_diagnostics_rows(debugging_actions),
        open_meetings_folder=RowView(
            label=menu.OPEN_MEETINGS_LABEL, action=controller.open_meetings_folder
        ),
        quit=RowView(label=menu.QUIT_LABEL),  # real quit callback is rumps-specific; see tray.py
    )


def recording_view_for(controller: TrayController) -> RecordingView:
    """Public so the 1 Hz tick can recompute just this piece and update the
    sidebar's record button in place rather than rebuilding the panel."""

    recorder = controller.recorder
    is_recording = recorder.is_recording
    duration = controller.recording_duration_seconds()
    audio_warning = bool(getattr(recorder, "recording_warning", None))
    return RecordingView(
        is_recording=is_recording,
        duration_seconds=duration,
        audio_warning=audio_warning,
        label=menu.recording_label(
            is_recording=is_recording,
            duration_seconds=duration,
            audio_warning=audio_warning,
        ),
    )


def _audio_mode_rows(audio_mode_menu: AudioModeMenu) -> tuple[RowView, ...]:
    return tuple(
        RowView(
            label=audio_mode_menu._mode_label(mode),
            action=lambda mode=mode: audio_mode_menu.select_mode(mode),
        )
        for mode in AUDIO_MODES
    )


def _recent_section(controller: TrayController) -> SectionView:
    meetings = controller.recent_meetings()
    return SectionView(
        title=menu.RECENT_HEADER,
        rows=tuple(
            RowView(
                label=menu.recent_meeting_label(item),
                action=lambda item=item: controller.open_meeting(item),
            )
            for item in meetings[:RECENT_MEETINGS_CAP]
        ),
        empty_label=menu.NO_MEETINGS_LABEL if not meetings else None,
    )


def _processing_section(controller: TrayController, actions: DebuggingActions) -> SectionView:
    """Meetings waiting on speaker review or Notes (SPEC F8, Debugging submenu)."""

    tasks = controller.pending_processing_tasks()
    return SectionView(
        title=menu.processing_header_label(len(tasks)),
        rows=tuple(
            RowView(
                label=menu.processing_task_label(task),
                tooltip=menu.processing_task_tooltip(task),
                action=lambda task=task: run_processing_task(
                    task,
                    review_speakers=actions.review_speakers,
                    generate_notes=actions.generate_notes,
                ),
            )
            for task in tasks
        ),
    )


def _recovered_section(controller: TrayController, actions: DebuggingActions) -> SectionView:
    recordings = controller.recovered_recordings()
    return SectionView(
        title=menu.recovered_header_label(len(recordings)),
        rows=tuple(
            RowView(
                label=menu.recovered_recording_label(item.meta.slug),
                tooltip=RECOVERED_ROW_TOOLTIP,
                action=lambda item=item: actions.process_recovered_recording(item),
            )
            for item in recordings
        ),
    )


def _readiness_rows(readiness_report: ReadinessReport | None) -> tuple[RowView, ...]:
    if readiness_report is None:
        return ()
    return tuple(
        RowView(label=readiness_menu_label(status), tooltip=readiness_tooltip(status))
        for status in readiness_report.statuses
    )


def _configuration_rows(actions: ConfigurationActions) -> tuple[RowView, ...]:
    capability_rows = tuple(
        RowView(
            label=f"{capability.label}...",
            action=lambda capability=capability: actions.open_capability(capability),
        )
        for capability in Capability
    )
    return (
        *capability_rows,
        RowView(
            label=menu.NOTES_PROMPT_LABEL,
            tooltip="Customize AI instructions and the local report layout used by Notes.",
            action=actions.open_notes_prompt,
        ),
        RowView(label=menu.AUTHORIZE_CALENDAR_LABEL, action=actions.authorize_calendar),
        RowView(label=menu.IMPORT_LEGACY_LABEL, action=actions.import_legacy),
    )


def _diagnostics_rows(actions: DebuggingActions) -> tuple[RowView, ...]:
    return (
        RowView(
            label=menu.LEGACY_RECOVERY_SCAN_LABEL,
            tooltip="Explicitly scan the old macOS temp location once.",
            action=actions.scan_legacy_recoveries,
        ),
        RowView(label=menu.SYNC_LABEL, tooltip=B2_SYNC_TOOLTIP, action=actions.sync_to_b2),
        RowView(
            label=menu.RETRY_PROCESSING_LABEL,
            tooltip=TRANSCRIPTION_RETRY_TOOLTIP,
            action=actions.retry_failed_processing,
        ),
        RowView(
            label=menu.RUN_DIAGNOSTICS_LABEL,
            tooltip=DIAGNOSTICS_TOOLTIP,
            action=actions.run_diagnostics,
        ),
        RowView(
            label=menu.TEST_NOTIFICATION_LABEL,
            tooltip=TEST_NOTIFICATION_TOOLTIP,
            action=actions.send_test_notification,
        ),
    )

"""Native configuration and debugging tray submenus."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from meeting_memory.types.capabilities import ReadinessReport
from meeting_memory.types.processing import ProcessingTask
from meeting_memory.ui import menu
from meeting_memory.ui.audio_modes import AudioModeMenu
from meeting_memory.ui.processing_actions import run_processing_task
from meeting_memory.ui.setup_readiness import readiness_menu_label, readiness_tooltip

B2_SYNC_TOOLTIP = "Upload meetings whose B2 backup is pending or failed."
TRANSCRIPTION_RETRY_TOOLTIP = (
    "Re-run AssemblyAI transcription using the saved local audio."
)
DIAGNOSTICS_TOOLTIP = (
    "Check all five capabilities without making optional services block recording."
)
TEST_NOTIFICATION_TOOLTIP = (
    "Send a local notification to verify macOS notification permissions."
)


@dataclass(frozen=True)
class ConfigurationActions:
    open_known_speakers: Callable[..., None]
    open_notes_prompt: Callable[..., None]
    open_preferences: Callable[..., None]


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


def configuration_submenu(
    rumps: Any,
    audio_mode_menu: AudioModeMenu,
    actions: ConfigurationActions,
) -> Any:
    submenu = rumps.MenuItem(menu.CONFIGURATION_LABEL)
    audio_mode_menu.add_items(submenu)
    submenu.add(rumps.MenuItem(menu.KNOWN_SPEAKERS_LABEL, actions.open_known_speakers))
    submenu.add(rumps.MenuItem(menu.NOTES_PROMPT_LABEL, actions.open_notes_prompt))
    submenu.add(rumps.MenuItem(menu.PREFERENCES_LABEL, actions.open_preferences))
    return submenu


def debugging_submenu(
    rumps: Any,
    *,
    processing_tasks: Sequence[ProcessingTask],
    recovered_recordings: Sequence[Any],
    readiness_report: ReadinessReport | None,
    actions: DebuggingActions,
) -> Any:
    submenu = rumps.MenuItem(menu.DEBUGGING_LABEL)
    _add_processing_tasks(rumps, submenu, processing_tasks, actions)
    _add_recovered_recordings(rumps, submenu, recovered_recordings, actions)
    submenu.add(
        _menu_item(
            rumps,
            menu.LEGACY_RECOVERY_SCAN_LABEL,
            lambda _sender: actions.scan_legacy_recoveries(),
            tooltip="Explicitly scan the old macOS temp location once.",
        )
    )
    submenu.add(
        _menu_item(
            rumps,
            menu.SYNC_LABEL,
            lambda _sender: actions.sync_to_b2(),
            tooltip=B2_SYNC_TOOLTIP,
        )
    )
    submenu.add(
        _menu_item(
            rumps,
            menu.RETRY_PROCESSING_LABEL,
            lambda _sender: actions.retry_failed_processing(),
            tooltip=TRANSCRIPTION_RETRY_TOOLTIP,
        )
    )
    submenu.add(None)
    if readiness_report is not None:
        for status in readiness_report.statuses:
            submenu.add(
                _menu_item(
                    rumps,
                    readiness_menu_label(status),
                    tooltip=readiness_tooltip(status),
                )
            )
    submenu.add(
        _menu_item(
            rumps,
            menu.RUN_DIAGNOSTICS_LABEL,
            actions.run_diagnostics,
            tooltip=DIAGNOSTICS_TOOLTIP,
        )
    )
    submenu.add(
        _menu_item(
            rumps,
            menu.TEST_NOTIFICATION_LABEL,
            actions.send_test_notification,
            tooltip=TEST_NOTIFICATION_TOOLTIP,
        )
    )
    return submenu


def _add_processing_tasks(
    rumps: Any,
    submenu: Any,
    tasks: Sequence[ProcessingTask],
    actions: DebuggingActions,
) -> None:
    count = len(tasks)
    empty_tooltip = "No meetings currently need review, notes, or a retry."
    submenu.add(
        _menu_item(
            rumps,
            menu.processing_header_label(count),
            tooltip=empty_tooltip if not tasks else "Meetings that still need your attention.",
        )
    )
    for task in tasks:
        submenu.add(
            _menu_item(
                rumps,
                menu.processing_task_label(task),
                callback=lambda _sender, item=task: run_processing_task(
                    item,
                    review_speakers=actions.review_speakers,
                    generate_notes=actions.generate_notes,
                ),
                tooltip=menu.processing_task_tooltip(task),
            )
        )
    submenu.add(None)


def _add_recovered_recordings(
    rumps: Any,
    submenu: Any,
    recordings: Sequence[Any],
    actions: DebuggingActions,
) -> None:
    if not recordings:
        return
    submenu.add(
        _menu_item(
            rumps,
            menu.recovered_header_label(len(recordings)),
            tooltip="Recordings saved after an interruption or unexpected app exit.",
        )
    )
    for recording in recordings:
        submenu.add(
            _menu_item(
                rumps,
                menu.recovered_recording_label(recording.meta.slug),
                callback=lambda _sender, item=recording: (
                    actions.process_recovered_recording(item)
                ),
                tooltip="Recover this recording and resume transcription.",
            )
        )
    submenu.add(None)


def _menu_item(
    rumps: Any,
    title: str,
    callback: Callable[..., None] | None = None,
    *,
    tooltip: str,
) -> Any:
    item = rumps.MenuItem(title, callback)
    item.tooltip = tooltip
    native_item = getattr(item, "_menuitem", None)
    set_tooltip = getattr(native_item, "setToolTip_", None)
    if callable(set_tooltip):
        set_tooltip(tooltip)
    return item

"""Tests for self-explanatory native tray submenus."""

from __future__ import annotations

from tray_fakes import FakeRumps

from meeting_memory.ui import menu
from meeting_memory.ui.submenus import DebuggingActions, debugging_submenu


def test_debugging_submenu_uses_explicit_actions_and_hover_help() -> None:
    submenu = debugging_submenu(
        FakeRumps(),
        processing_tasks=[],
        recovered_recordings=[],
        doctor_results=[],
        actions=_actions(),
    )
    items = {item.title: item for item in submenu.items if item is not None}

    assert list(items) == [
        menu.processing_header_label(0),
        menu.LEGACY_RECOVERY_SCAN_LABEL,
        menu.SYNC_LABEL,
        menu.RETRY_PROCESSING_LABEL,
        menu.RUN_DIAGNOSTICS_LABEL,
        menu.TEST_NOTIFICATION_LABEL,
    ]
    assert items[menu.processing_header_label(0)].tooltip.startswith("No meetings")
    assert items[menu.SYNC_LABEL].tooltip.startswith("Upload meetings")
    assert items[menu.RETRY_PROCESSING_LABEL].tooltip.startswith("Re-run AssemblyAI")
    assert items[menu.RUN_DIAGNOSTICS_LABEL].tooltip.startswith("Check credentials")
    assert items[menu.TEST_NOTIFICATION_LABEL].tooltip.startswith("Send a local")


def _actions() -> DebuggingActions:
    return DebuggingActions(
        review_speakers=lambda _path: None,
        generate_notes=lambda _path: None,
        process_recovered_recording=lambda _recording: None,
        scan_legacy_recoveries=lambda: None,
        sync_to_b2=lambda: None,
        retry_failed_processing=lambda: None,
        run_diagnostics=lambda _sender=None: None,
        send_test_notification=lambda _sender=None: None,
    )

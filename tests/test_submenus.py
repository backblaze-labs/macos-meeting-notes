"""Tests for self-explanatory native tray submenus."""

from __future__ import annotations

from tray_fakes import FakeRumps

from meeting_memory.types.capabilities import (
    Capability,
    CapabilityState,
    CapabilityStatus,
    ReadinessReport,
)
from meeting_memory.ui import menu
from meeting_memory.ui.submenus import (
    ConfigurationActions,
    DebuggingActions,
    configuration_submenu,
    debugging_submenu,
)


def test_configuration_callbacks_accept_rumps_sender_and_preserve_native_actions() -> None:
    calls = []
    actions = ConfigurationActions(
        open_capability=lambda capability: calls.append(capability),
        import_legacy=lambda: calls.append("migration"),
        authorize_calendar=lambda: calls.append("authorization"),
        open_notes_prompt=lambda: calls.append("prompt"),
    )
    submenu = configuration_submenu(FakeRumps(), None, actions)
    items = {item.title: item for item in submenu.items if item is not None}

    for capability in Capability:
        items[f"{capability.label}..."].callback(object())
    items[menu.NOTES_PROMPT_LABEL].callback(object())
    items[menu.AUTHORIZE_CALENDAR_LABEL].callback(object())
    items[menu.IMPORT_LEGACY_LABEL].callback(object())

    assert calls == [*Capability, "prompt", "authorization", "migration"]


def test_setup_configuration_keeps_prompt_visible_but_safely_disabled() -> None:
    submenu = configuration_submenu(
        FakeRumps(),
        None,
        ConfigurationActions(lambda _capability: None, lambda: None, lambda: None, lambda: None),
        notes_prompt_available=False,
    )
    items = {item.title: item for item in submenu.items if item is not None}

    assert items[menu.NOTES_PROMPT_LABEL].callback is None
    assert "Recording Core setup" in items[menu.NOTES_PROMPT_LABEL].tooltip


def test_debugging_submenu_uses_explicit_actions_and_hover_help() -> None:
    submenu = debugging_submenu(
        FakeRumps(),
        processing_tasks=[],
        recovered_recordings=[],
        readiness_report=None,
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
    assert items[menu.RUN_DIAGNOSTICS_LABEL].tooltip.startswith("Check all five")
    assert items[menu.TEST_NOTIFICATION_LABEL].tooltip.startswith("Send a local")


def test_debugging_submenu_renders_all_five_capability_states_and_actions() -> None:
    report = ReadinessReport(
        tuple(
            CapabilityStatus(
                capability,
                CapabilityState.UNCONFIGURED,
                f"{capability.label} summary.",
                f"Configure {capability.label}.",
            )
            for capability in Capability
        )
    )
    submenu = debugging_submenu(
        FakeRumps(),
        processing_tasks=[],
        recovered_recordings=[],
        readiness_report=report,
        actions=_actions(),
    )
    items = {item.title: item for item in submenu.items if item is not None}

    labels = [f"{capability.label}: Unconfigured" for capability in Capability]
    assert all(label in items for label in labels)
    assert "Action: Configure Recording Core." in items[labels[0]].tooltip


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

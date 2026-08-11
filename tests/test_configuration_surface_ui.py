"""Main-thread stale filtering and terminal-copy tests for the native surface."""

from __future__ import annotations

from pathlib import Path

from configuration_surface_fakes import configuration_view
from tray_fakes import FakeRumps

from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration_editing import (
    ConfigurationOperationId,
    ConfigurationSaveOutcome,
    ConfigurationSaveState,
)
from meeting_memory.types.configuration_migration import (
    MigrationOutcome,
    MigrationOutcomeState,
)
from meeting_memory.types.configuration_surface import (
    ConfigurationOpened,
    ConfigurationSaved,
    MigrationApplied,
    PromptDestination,
    PromptDraft,
    PromptLoaded,
    PromptOperationState,
    PromptOutcome,
    PromptSaved,
    SurfaceOperationKind,
)
from meeting_memory.ui import configuration_surface
from meeting_memory.ui.configuration_surface import ConfigurationSurfaceUI


def test_configuration_cancel_acknowledges_then_releases_bound_edit(monkeypatch) -> None:
    coordinator = Coordinator()
    rumps = FakeRumps()
    operation = coordinator.begin(SurfaceOperationKind.CONFIGURATION)
    view = configuration_view(Capability.BACKUP)
    monkeypatch.setattr(configuration_surface, "open_configuration_form", lambda _view: None)
    ui = ConfigurationSurfaceUI(coordinator, rumps)

    assert ui.handle_event(ConfigurationOpened(operation, view)) is True

    assert coordinator.acknowledged == [(SurfaceOperationKind.CONFIGURATION, operation)]
    assert coordinator.cancelled == [view.edit_id]
    assert coordinator.saved == []


def test_duplicate_or_stale_terminal_event_is_ignored() -> None:
    coordinator = Coordinator()
    rumps = FakeRumps()
    operation = coordinator.begin(SurfaceOperationKind.CONFIGURATION)
    outcome = ConfigurationSaveOutcome(
        ConfigurationSaveState.SAVED,
        Capability.BACKUP,
        "Saved.",
        "Restart.",
    )
    event = ConfigurationSaved(operation, outcome, True)
    ui = ConfigurationSurfaceUI(coordinator, rumps)

    ui.handle_event(event)
    ui.handle_event(event)

    assert rumps.alerts == [("Saved.", "Restart.")]


def test_save_terminal_renders_restart_and_process_override_truth() -> None:
    coordinator = Coordinator()
    rumps = FakeRumps()
    operation = coordinator.begin(SurfaceOperationKind.CONFIGURATION)
    outcome = ConfigurationSaveOutcome(
        ConfigurationSaveState.SAVED,
        Capability.BACKUP,
        "Configuration saved.",
        "Restart if prompted.",
        restart_required=True,
        pause_current_session=True,
        process_reenables=True,
    )

    ConfigurationSurfaceUI(coordinator, rumps).handle_event(
        ConfigurationSaved(operation, outcome, True)
    )

    message = rumps.alerts[0][1]
    assert "Quit and reopen Meeting Memory" in message
    assert "Process environment settings will re-enable" in message


def test_save_terminal_renders_legacy_compatibility_restart_truth() -> None:
    coordinator = Coordinator()
    rumps = FakeRumps()
    operation = coordinator.begin(SurfaceOperationKind.CONFIGURATION)
    outcome = ConfigurationSaveOutcome(
        ConfigurationSaveState.SAVED,
        Capability.NOTES,
        "Configuration saved.",
        "Review the result.",
        restart_required=True,
        legacy_reenables=True,
    )

    ConfigurationSurfaceUI(coordinator, rumps).handle_event(
        ConfigurationSaved(operation, outcome, True)
    )

    assert "Legacy .env compatibility settings will re-enable" in rumps.alerts[0][1]


def test_activation_uncertain_legacy_copy_does_not_claim_visibility() -> None:
    coordinator = Coordinator()
    rumps = FakeRumps()
    operation = coordinator.begin(SurfaceOperationKind.CONFIGURATION)
    outcome = ConfigurationSaveOutcome(
        ConfigurationSaveState.ACTIVATION_UNCERTAIN,
        Capability.NOTES,
        "Activation uncertain.",
        "Restart and check setup.",
        restart_required=True,
        pause_current_session=True,
        legacy_reenables=True,
    )

    ConfigurationSurfaceUI(coordinator, rumps).handle_event(
        ConfigurationSaved(operation, outcome, True)
    )

    message = rumps.alerts[0][1]
    assert "may re-enable" in message
    assert "will re-enable" not in message


def test_session_pause_failure_requires_immediate_quit_copy() -> None:
    coordinator = Coordinator()
    rumps = FakeRumps()
    operation = coordinator.begin(SurfaceOperationKind.CONFIGURATION)
    outcome = ConfigurationSaveOutcome(
        ConfigurationSaveState.SESSION_PAUSED,
        Capability.NOTES,
        "Paused.",
        "Remove process settings.",
        pause_current_session=True,
        process_reenables=True,
    )

    ConfigurationSurfaceUI(coordinator, rumps).handle_event(
        ConfigurationSaved(operation, outcome, False)
    )

    assert "pause could not be confirmed" in rumps.alerts[0][1]
    assert "quit Meeting Memory" in rumps.alerts[0][1]


def test_applied_migration_requires_relaunch_before_use() -> None:
    coordinator = Coordinator()
    rumps = FakeRumps()
    operation = coordinator.begin(SurfaceOperationKind.MIGRATION)
    outcome = MigrationOutcome(
        MigrationOutcomeState.APPLIED,
        (Capability.RECORDING_CORE, Capability.TRANSCRIPTION),
        "Imported.",
        "No further action is required.",
    )

    ConfigurationSurfaceUI(coordinator, rumps).handle_event(
        MigrationApplied(operation, outcome, True)
    )

    assert "Quit and reopen Meeting Memory" in rumps.alerts[0][1]


def test_prompt_load_consumes_private_draft_only_after_current_ack(monkeypatch) -> None:
    coordinator = Coordinator()
    rumps = FakeRumps()
    operation = coordinator.begin(SurfaceOperationKind.NOTES_PROMPT)
    coordinator.drafts[operation] = PromptDraft("private prompt sentinel")
    seen: list[str] = []
    monkeypatch.setattr(
        configuration_surface,
        "edit_prompt",
        lambda draft: seen.append(draft.text) or None,
    )
    outcome = PromptOutcome(
        PromptOperationState.LOADED,
        "Loaded.",
        "Review.",
    )

    ConfigurationSurfaceUI(coordinator, rumps).handle_event(PromptLoaded(operation, outcome))

    assert seen == ["private prompt sentinel"]
    assert "sentinel" not in repr(rumps.alerts)


def test_prompt_save_displays_redacted_destination_only_in_ui_copy() -> None:
    coordinator = Coordinator()
    rumps = FakeRumps()
    operation = coordinator.begin(SurfaceOperationKind.NOTES_PROMPT)
    destination = PromptDestination(Path("/private/path-sentinel/prompt.md"))
    outcome = PromptOutcome(
        PromptOperationState.SAVED,
        "Saved.",
        "The next Notes run will use it.",
        destination,
    )

    event = PromptSaved(operation, outcome)
    ConfigurationSurfaceUI(coordinator, rumps).handle_event(event)

    assert "/private/path-sentinel/prompt.md" in rumps.alerts[0][1]
    assert "path-sentinel" not in repr(event)


def test_calendar_confirmation_failure_is_sanitized_and_does_not_start_worker(
    monkeypatch,
) -> None:
    coordinator = Coordinator()
    rumps = FakeRumps()
    monkeypatch.setattr(
        configuration_surface,
        "confirm_calendar_authorization",
        lambda: (_ for _ in ()).throw(RuntimeError("appkit-sentinel")),
    )

    ConfigurationSurfaceUI(coordinator, rumps).authorize_calendar()

    assert rumps.alerts == [
        (
            "Calendar authorization could not be opened safely.",
            "Close other dialogs and try the explicit authorization action again.",
        )
    ]
    assert "appkit-sentinel" not in repr(rumps.alerts)


class Coordinator:
    def __init__(self) -> None:
        self.current = {}
        self.acknowledged = []
        self.cancelled = []
        self.saved = []
        self.drafts = {}
        self.index = 0

    def begin(self, kind):
        self.index += 1
        operation = ConfigurationOperationId(f"{self.index:032x}")
        self.current[kind] = operation
        return operation

    def is_current(self, kind, operation):
        return self.current.get(kind) == operation

    def acknowledge(self, kind, operation):
        if not self.is_current(kind, operation):
            return False
        self.current.pop(kind)
        self.acknowledged.append((kind, operation))
        return True

    def cancel_configuration(self, edit_id):
        self.cancelled.append(edit_id)
        return True

    def save_configuration(self, change):
        self.saved.append(change)
        return self.begin(SurfaceOperationKind.CONFIGURATION)

    def apply_migration(self, _confirmation):
        return self.begin(SurfaceOperationKind.MIGRATION)

    def save_prompt(self, _draft):
        return self.begin(SurfaceOperationKind.NOTES_PROMPT)

    def cancel_prompt(self, operation):
        self.drafts.pop(operation, None)
        return True

    def cancel_migration(self, _preview_id):
        return True

    def consume_prompt(self, operation):
        return self.drafts.pop(operation, None)

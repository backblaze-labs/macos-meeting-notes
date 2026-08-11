"""Main-thread controller for the shared native configuration surface."""

from __future__ import annotations

from collections.abc import Callable

from meeting_memory.service.configuration_surface import ConfigurationSurfaceCoordinator
from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration_editing import ConfigurationSaveState
from meeting_memory.types.configuration_migration import (
    MigrationOutcomeState,
    MigrationPreviewState,
)
from meeting_memory.types.configuration_surface import (
    CalendarAuthorizationFinished,
    ConfigurationOpened,
    ConfigurationOpenFailed,
    ConfigurationSaved,
    MigrationApplied,
    MigrationPreviewed,
    MigrationPreviewFailed,
    PromptLoaded,
    PromptOperationState,
    PromptSaved,
    SurfaceOperationKind,
)
from meeting_memory.ui.configuration_forms import open_configuration_form
from meeting_memory.ui.migration_form import (
    choose_legacy_environment_file,
    confirm_calendar_authorization,
    open_migration_preview,
)
from meeting_memory.ui.prompt_form import edit_prompt


class ConfigurationSurfaceUI:
    """Open standard AppKit controls and route all storage work to workers."""

    def __init__(
        self,
        coordinator: ConfigurationSurfaceCoordinator,
        rumps_module,
        *,
        rebuild_menu: Callable[[], None] = lambda: None,
    ) -> None:
        self._coordinator = coordinator
        self._rumps = rumps_module
        self._rebuild = rebuild_menu
        self._modal = False

    def open_capability(self, capability: Capability) -> None:
        if self._modal:
            return
        if self._coordinator.open_configuration(capability) is None:
            self._busy()

    def preview_migration(self) -> None:
        if self._modal:
            return
        source = None
        if self._coordinator.migration_source_required:
            self._modal = True
            try:
                source = choose_legacy_environment_file()
            except Exception:
                self._alert(
                    "Legacy configuration could not be selected safely.",
                    "Choose a regular .env file and try again.",
                )
            finally:
                self._modal = False
            if source is None:
                return
        if self._coordinator.preview_migration(source_path=source) is None:
            self._busy()

    def authorize_calendar(self) -> None:
        if self._modal:
            return
        self._modal = True
        confirmed = False
        try:
            confirmed = confirm_calendar_authorization()
        except Exception:
            self._alert(
                "Calendar authorization could not be opened safely.",
                "Close other dialogs and try the explicit authorization action again.",
            )
        finally:
            self._modal = False
        if confirmed and self._coordinator.authorize_calendar() is None:
            self._busy()

    def edit_notes_prompt(self) -> None:
        if self._modal:
            return
        if self._coordinator.load_prompt() is None:
            self._busy()

    def handle_event(self, event: object) -> bool:
        kind = _event_kind(event)
        if kind is None:
            return False
        if not self._coordinator.is_current(kind, event.operation_id):
            return True
        if not self._coordinator.acknowledge(kind, event.operation_id):
            return True
        if isinstance(event, ConfigurationOpened):
            self._configuration_opened(event)
        elif isinstance(event, ConfigurationOpenFailed):
            self._alert(event.summary, event.action)
        elif isinstance(event, ConfigurationSaved):
            self._terminal(event.outcome.summary, event.outcome.action, event)
        elif isinstance(event, MigrationPreviewed):
            self._migration_previewed(event)
        elif isinstance(event, MigrationPreviewFailed):
            self._alert(event.summary, event.action)
        elif isinstance(event, MigrationApplied):
            self._terminal(event.outcome.summary, event.outcome.action, event)
        elif isinstance(event, CalendarAuthorizationFinished):
            self._alert(event.outcome.summary, event.outcome.action)
        elif isinstance(event, PromptLoaded):
            self._prompt_loaded(event)
        elif isinstance(event, PromptSaved):
            action = event.outcome.action
            if event.outcome.destination is not None:
                action = f"{action} Saved to {event.outcome.destination.value}."
            self._alert(event.outcome.summary, action)
        self._rebuild()
        return True

    def _configuration_opened(self, event: ConfigurationOpened) -> None:
        self._modal = True
        try:
            try:
                change = open_configuration_form(event.configuration)
            except ValueError:
                change = None
                self._alert(
                    "Configuration was not saved.",
                    "Complete credential fields together, then reopen the form.",
                )
            except Exception:
                change = None
                self._alert(
                    "Configuration form could not be opened safely.",
                    "Close other dialogs and try again.",
                )
        finally:
            self._modal = False
        if change is None:
            self._coordinator.cancel_configuration(event.configuration.edit_id)
        elif self._coordinator.save_configuration(change) is None:
            self._alert(
                "Configuration save did not start.",
                "Close the form and try again.",
            )

    def _migration_previewed(self, event: MigrationPreviewed) -> None:
        if event.preview.state is not MigrationPreviewState.READY:
            self._alert(event.preview.summary, event.preview.action)
            return
        self._modal = True
        try:
            confirmation = open_migration_preview(event.preview)
        except Exception:
            confirmation = None
            self._alert(
                "Migration preview could not be shown safely.",
                "Close other dialogs and open a new preview.",
            )
        finally:
            self._modal = False
        if confirmation is None:
            self._coordinator.cancel_migration(event.preview.preview_id)
        elif self._coordinator.apply_migration(confirmation) is None:
            self._busy()

    def _prompt_loaded(self, event: PromptLoaded) -> None:
        if event.outcome.state is not PromptOperationState.LOADED:
            self._alert(event.outcome.summary, event.outcome.action)
            return
        draft = self._coordinator.consume_prompt(event.operation_id)
        if draft is None:
            self._alert("Notes prompt expired.", "Open the Notes prompt again.")
            return
        self._modal = True
        try:
            updated = edit_prompt(draft)
        except Exception:
            updated = None
            self._alert(
                "Notes prompt editor could not be opened safely.",
                "Close other dialogs and try again.",
            )
        finally:
            self._modal = False
        if updated is None:
            self._coordinator.cancel_prompt(event.operation_id)
        elif self._coordinator.save_prompt(updated) is None:
            self._busy()

    def _terminal(self, summary: str, action: str, event) -> None:
        outcome = event.outcome
        if getattr(outcome, "restart_required", False):
            action = f"{action} Quit and reopen Meeting Memory to use the saved configuration."
        if getattr(outcome, "process_reenables", False):
            action = (
                f"{action} Process environment settings will re-enable this capability "
                "after restart."
            )
        outcome_state = getattr(outcome, "state", None)
        legacy_activated = outcome_state in {
            ConfigurationSaveState.SAVED,
            ConfigurationSaveState.SAVED_CLEANUP_FAILED,
            ConfigurationSaveState.DURABILITY_UNCERTAIN,
        }
        if legacy_activated and getattr(outcome, "legacy_reenables", False):
            action = (
                f"{action} Legacy .env compatibility settings will re-enable this "
                "capability after restart."
            )
        elif outcome_state is ConfigurationSaveState.ACTIVATION_UNCERTAIN and getattr(
            outcome, "legacy_reenables", False
        ):
            action = (
                f"{action} Legacy .env compatibility settings may re-enable this "
                "capability; check setup after restart."
            )
        if isinstance(event, MigrationApplied) and outcome.state in {
            MigrationOutcomeState.APPLIED,
            MigrationOutcomeState.DURABILITY_UNCERTAIN,
            MigrationOutcomeState.ACTIVATION_UNCERTAIN,
        }:
            action = f"{action} Quit and reopen Meeting Memory before using migrated settings."
        if not event.runtime_pause_succeeded:
            action = (
                f"{action} Current-session pause could not be confirmed; "
                "quit Meeting Memory before continuing."
            )
        self._alert(summary, action)

    def _busy(self) -> None:
        self._alert("Configuration is already in progress.", "Finish the open action first.")

    def _alert(self, summary: str, action: str) -> None:
        self._rumps.alert(title=summary, message=action)


def _event_kind(event: object) -> SurfaceOperationKind | None:
    if isinstance(event, (ConfigurationOpened, ConfigurationOpenFailed, ConfigurationSaved)):
        return SurfaceOperationKind.CONFIGURATION
    if isinstance(event, (MigrationPreviewed, MigrationPreviewFailed, MigrationApplied)):
        return SurfaceOperationKind.MIGRATION
    if isinstance(event, CalendarAuthorizationFinished):
        return SurfaceOperationKind.CALENDAR_AUTHORIZATION
    if isinstance(event, (PromptLoaded, PromptSaved)):
        return SurfaceOperationKind.NOTES_PROMPT
    return None

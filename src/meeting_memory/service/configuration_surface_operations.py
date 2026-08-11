"""Side-effect orchestration used by the native configuration worker."""

from collections.abc import Mapping

from meeting_memory.service.calendar_authorization import CalendarAuthorizationService
from meeting_memory.service.configuration_editing import CapabilityConfigurationService
from meeting_memory.service.configuration_editing_outcomes import configuration_outcome
from meeting_memory.service.configuration_migration import EnvironmentMigrationService
from meeting_memory.service.configuration_migration_outcomes import migration_outcome
from meeting_memory.service.runtime_capabilities import RuntimeCapabilityPause
from meeting_memory.types.calendar_authorization import (
    CalendarAuthorizationOutcome,
    CalendarAuthorizationState,
)
from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration_editing import (
    ConfigurationChange,
    ConfigurationOperationId,
    ConfigurationSaveState,
)
from meeting_memory.types.configuration_migration import (
    MigrationConfirmation,
    MigrationOutcomeState,
)
from meeting_memory.types.configuration_surface import (
    CalendarAuthorizationFinished,
    ConfigurationOpened,
    ConfigurationOpenFailed,
    ConfigurationSaved,
    MigrationApplied,
)

_MIGRATION_PAUSE_STATES = {
    MigrationOutcomeState.APPLIED,
    MigrationOutcomeState.DURABILITY_UNCERTAIN,
    MigrationOutcomeState.ACTIVATION_UNCERTAIN,
}


def surface_is_busy(active: Mapping, *bindings: object) -> bool:
    return bool(active or any(binding is not None for binding in bindings))


def failed_configuration_save(
    operation: ConfigurationOperationId,
    capability: Capability,
) -> ConfigurationSaved:
    return ConfigurationSaved(
        operation,
        configuration_outcome(ConfigurationSaveState.FAILED, capability),
        True,
    )


def failed_migration_apply(
    operation: ConfigurationOperationId,
    confirmation: MigrationConfirmation,
) -> MigrationApplied:
    return MigrationApplied(
        operation,
        migration_outcome(MigrationOutcomeState.FAILED, confirmation.selected),
        True,
    )


def open_configuration(
    service: CapabilityConfigurationService,
    operation: ConfigurationOperationId,
    capability: Capability,
):
    try:
        return ConfigurationOpened(operation, service.open(capability))
    except Exception:
        return ConfigurationOpenFailed(operation, capability)


def save_configuration(
    service: CapabilityConfigurationService,
    pause: RuntimeCapabilityPause,
    operation: ConfigurationOperationId,
    change: ConfigurationChange,
) -> ConfigurationSaved:
    outcome = service.save(change)
    pause_ok = not outcome.pause_current_session or pause.pause(outcome.capability)
    return ConfigurationSaved(operation, outcome, pause_ok)


def apply_migration(
    service: EnvironmentMigrationService,
    pause: RuntimeCapabilityPause,
    operation: ConfigurationOperationId,
    confirmation: MigrationConfirmation,
) -> MigrationApplied:
    outcome = service.apply(confirmation)
    pause_ok = True
    if outcome.state in _MIGRATION_PAUSE_STATES:
        results = tuple(
            pause.pause(capability)
            for capability in outcome.selected
            if capability is not Capability.RECORDING_CORE
        )
        pause_ok = all(results)
    return MigrationApplied(operation, outcome, pause_ok)


def authorize_calendar(
    service: CalendarAuthorizationService,
    operation: ConfigurationOperationId,
) -> CalendarAuthorizationFinished:
    return CalendarAuthorizationFinished(operation, service.authorize())


def failed_authorization(operation: ConfigurationOperationId) -> CalendarAuthorizationFinished:
    return CalendarAuthorizationFinished(
        operation,
        CalendarAuthorizationOutcome(
            CalendarAuthorizationState.FAILED,
            "Calendar authorization failed.",
            "Check setup and try the explicit authorization action again.",
        ),
    )

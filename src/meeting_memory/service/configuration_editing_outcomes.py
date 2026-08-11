"""Fixed, sanitized outcomes for native configuration editing."""

from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration_editing import (
    ConfigurationSaveOutcome,
    ConfigurationSaveState,
)

_MESSAGES = {
    ConfigurationSaveState.SAVED: (
        "Configuration saved.",
        "Restart if prompted.",
    ),
    ConfigurationSaveState.SAVED_CLEANUP_FAILED: (
        "Configuration saved; old credential cleanup needs attention.",
        "Restart, then check Keychain before editing again.",
    ),
    ConfigurationSaveState.SESSION_PAUSED: (
        "This capability is paused for the current session.",
        "Remove its process environment settings to keep it disabled after restart.",
    ),
    ConfigurationSaveState.UNCHANGED: (
        "No changes were saved.",
        "Nothing else is needed.",
    ),
    ConfigurationSaveState.REJECTED: (
        "Configuration was not saved.",
        "Review the form and try again.",
    ),
    ConfigurationSaveState.PREFERENCES_CONFLICT: (
        "Configuration changed elsewhere.",
        "Reopen the form and try again.",
    ),
    ConfigurationSaveState.KEYCHAIN_FAILED: (
        "Credential could not be saved.",
        "Check Keychain access and try again.",
    ),
    ConfigurationSaveState.DURABILITY_UNCERTAIN: (
        "Configuration may be saved.",
        "Restart and check setup before retrying.",
    ),
    ConfigurationSaveState.ACTIVATION_UNCERTAIN: (
        "Configuration activation is uncertain.",
        "Restart and check setup; do not retry automatically.",
    ),
    ConfigurationSaveState.CLEANUP_FAILED: (
        "Credential cleanup needs attention.",
        "Check Keychain before trying again.",
    ),
    ConfigurationSaveState.FAILED: (
        "Configuration could not be saved.",
        "Reopen the form and try again.",
    ),
}


def configuration_outcome(
    state: ConfigurationSaveState,
    capability: Capability,
    *,
    restart: bool = False,
    pause: bool = False,
    process_present: bool = False,
    process_reenables: bool = False,
    legacy_reenables: bool = False,
) -> ConfigurationSaveOutcome:
    summary, action = _MESSAGES[state]
    return ConfigurationSaveOutcome(
        state,
        capability,
        summary,
        action,
        restart,
        pause,
        process_present,
        process_reenables,
        legacy_reenables,
    )

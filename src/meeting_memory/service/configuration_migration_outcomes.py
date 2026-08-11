"""Sanitized previews and outcomes for explicit environment migration."""

from __future__ import annotations

from meeting_memory.service.configuration_migration_plan import build_migration_plan
from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration import AppPreferences, SettingKey
from meeting_memory.types.configuration_migration import (
    MigrationCandidate,
    MigrationOutcome,
    MigrationOutcomeState,
    MigrationPreview,
    MigrationPreviewId,
    MigrationPreviewState,
)


def migration_preview_empty(
    preview_id: MigrationPreviewId,
    process_keys: frozenset[SettingKey],
    candidates: tuple[MigrationCandidate, ...] | None = None,
) -> MigrationPreview:
    safe = candidates or build_migration_plan({}, AppPreferences(), process_keys).candidates
    return MigrationPreview(
        preview_id,
        MigrationPreviewState.EMPTY,
        safe,
        "No safe legacy configuration candidates are available.",
        "Keep the current configuration or open a new preview after updating it.",
    )


def migration_preview_failed(
    preview_id: MigrationPreviewId,
    process_keys: frozenset[SettingKey],
    candidates: tuple[MigrationCandidate, ...] | None = None,
) -> MigrationPreview:
    raw = candidates or build_migration_plan({}, AppPreferences(), process_keys).candidates
    blocked = tuple(MigrationCandidate(item.capability, item.fields, False) for item in raw)
    return MigrationPreview(
        preview_id,
        MigrationPreviewState.FAILED,
        blocked,
        "Legacy configuration could not be previewed safely.",
        "Repair the local configuration source and open a new preview.",
    )


_OUTCOME_MESSAGES = {
    MigrationOutcomeState.APPLIED: (
        "Selected legacy configuration was migrated.",
        "No further action is required.",
    ),
    MigrationOutcomeState.STALE_SOURCE: (
        "Legacy configuration changed before activation.",
        "Open a new preview and confirm the current configuration.",
    ),
    MigrationOutcomeState.PREFERENCES_CONFLICT: (
        "App preferences changed before activation.",
        "Open a new preview and confirm the current configuration.",
    ),
    MigrationOutcomeState.KEYCHAIN_FAILED: (
        "A selected credential could not be stored.",
        "Unlock Keychain, then open a new preview and retry.",
    ),
    MigrationOutcomeState.DURABILITY_UNCERTAIN: (
        "Migration is visible, but preference durability is uncertain.",
        "Do not retry automatically; restart and check configuration first.",
    ),
    MigrationOutcomeState.ACTIVATION_UNCERTAIN: (
        "Migration activation could not be determined safely.",
        "Do not retry automatically; restart and check configuration first.",
    ),
    MigrationOutcomeState.CLEANUP_FAILED: (
        "Migration was not activated and inactive credential cleanup needs attention.",
        "Open a new preview before retrying; existing configuration remains active.",
    ),
    MigrationOutcomeState.REJECTED: (
        "Migration confirmation was rejected.",
        "Open a new preview and explicitly confirm a valid selection.",
    ),
    MigrationOutcomeState.FAILED: (
        "Migration could not be activated.",
        "Open a new preview and retry after checking app preferences.",
    ),
}


def migration_outcome(
    state: MigrationOutcomeState,
    selected: tuple[Capability, ...],
) -> MigrationOutcome:
    summary, action = _OUTCOME_MESSAGES[state]
    return MigrationOutcome(state, selected, summary, action)

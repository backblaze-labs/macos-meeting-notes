"""Preference-CAS visibility classification for explicit migration."""

from __future__ import annotations

from collections.abc import Callable

from meeting_memory.types.configuration import PreferenceSnapshot
from meeting_memory.types.configuration_migration import MigrationOutcomeState


def classify_cas_visibility(
    reader: Callable[[], PreferenceSnapshot],
    expected: PreferenceSnapshot,
    intended: PreferenceSnapshot,
) -> MigrationOutcomeState:
    """Reload once and classify only states that are proven visible."""

    try:
        visible = reader()
    except Exception:
        return MigrationOutcomeState.ACTIVATION_UNCERTAIN
    if not isinstance(visible, PreferenceSnapshot):
        return MigrationOutcomeState.ACTIVATION_UNCERTAIN
    if visible == intended:
        return MigrationOutcomeState.DURABILITY_UNCERTAIN
    if visible == expected:
        return MigrationOutcomeState.FAILED
    return MigrationOutcomeState.ACTIVATION_UNCERTAIN

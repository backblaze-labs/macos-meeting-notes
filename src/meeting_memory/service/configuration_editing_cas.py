"""Preference visibility and exact generation cleanup for configuration edits."""

from __future__ import annotations

from typing import Protocol

from meeting_memory.repo.secret_store import SecretStoreCleanupUncertain
from meeting_memory.service.preference_store import (
    PreferencesConflictError,
    PreferencesDurabilityUncertain,
)
from meeting_memory.types.configuration import (
    AppPreferences,
    PreferenceSnapshot,
    SecretRef,
)
from meeting_memory.types.configuration_editing import ConfigurationChange, ConfigurationSaveState


class CasPreferenceStore(Protocol):
    def load_snapshot(self) -> PreferenceSnapshot:
        raise NotImplementedError

    def compare_and_swap(
        self,
        expected: PreferenceSnapshot,
        replacement: AppPreferences,
    ) -> PreferenceSnapshot:
        raise NotImplementedError


class CasSecretStore(Protocol):
    def delete(self, ref: SecretRef) -> None:
        raise NotImplementedError

    def write_new(self, bundle) -> SecretRef:
        raise NotImplementedError


def write_new_secret(
    secrets: CasSecretStore,
    change: ConfigurationChange,
    snapshot: PreferenceSnapshot,
) -> SecretRef | ConfigurationSaveState | None:
    if change.secret is None:
        return None
    try:
        ref = secrets.write_new(change.secret)
    except SecretStoreCleanupUncertain:
        return ConfigurationSaveState.CLEANUP_FAILED
    except Exception:
        return ConfigurationSaveState.KEYCHAIN_FAILED
    if (
        not isinstance(ref, SecretRef)
        or ref.secret_id is not change.secret.secret_id
        or ref in snapshot.preferences.secret_refs
    ):
        return ConfigurationSaveState.CLEANUP_FAILED
    return ref


def save_replacement(
    preferences: CasPreferenceStore,
    secrets: CasSecretStore,
    expected: PreferenceSnapshot,
    replacement: AppPreferences,
    intended: PreferenceSnapshot,
    new_ref: SecretRef | None,
) -> ConfigurationSaveState:
    try:
        saved = preferences.compare_and_swap(expected, replacement)
    except PreferencesConflictError:
        return _cleanup(secrets, new_ref, ConfigurationSaveState.PREFERENCES_CONFLICT)
    except PreferencesDurabilityUncertain as exc:
        if exc.snapshot == intended:
            return ConfigurationSaveState.DURABILITY_UNCERTAIN
        return _classify(preferences, secrets, expected, intended, new_ref)
    except Exception:
        return _classify(preferences, secrets, expected, intended, new_ref)
    if saved == intended:
        return ConfigurationSaveState.SAVED
    return _classify(preferences, secrets, expected, intended, new_ref)


def _classify(
    preferences: CasPreferenceStore,
    secrets: CasSecretStore,
    expected: PreferenceSnapshot,
    intended: PreferenceSnapshot,
    new_ref: SecretRef | None,
) -> ConfigurationSaveState:
    try:
        visible = preferences.load_snapshot()
    except Exception:
        return ConfigurationSaveState.ACTIVATION_UNCERTAIN
    if visible == intended:
        return ConfigurationSaveState.DURABILITY_UNCERTAIN
    if visible == expected:
        return _cleanup(secrets, new_ref, ConfigurationSaveState.FAILED)
    return ConfigurationSaveState.ACTIVATION_UNCERTAIN


def _cleanup(
    secrets: CasSecretStore,
    ref: SecretRef | None,
    state: ConfigurationSaveState,
) -> ConfigurationSaveState:
    if ref is None:
        return state
    try:
        secrets.delete(ref)
    except Exception:
        return ConfigurationSaveState.CLEANUP_FAILED
    return state

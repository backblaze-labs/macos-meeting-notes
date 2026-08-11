"""Explicit app-owned capability configuration with private edit bindings."""

from __future__ import annotations

import os
import threading
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from meeting_memory.config.resolution import resolve_configuration
from meeting_memory.config.schema import definitions_for
from meeting_memory.repo.secret_store import KeychainSecretStore
from meeting_memory.service.configuration_editing_cas import (
    save_replacement,
    write_new_secret,
)
from meeting_memory.service.configuration_editing_outcomes import configuration_outcome
from meeting_memory.service.configuration_editing_support import (
    editable_fields,
    editing_legacy_source,
    legacy_reenables,
    replacement_preferences,
    secret_id_for_capability,
    valid_change,
)
from meeting_memory.service.configuration_sources import (
    load_legacy_environment,
    read_secret_materials,
)
from meeting_memory.service.preference_store import (
    PreferenceStore,
    snapshot_for_preferences,
)
from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration import (
    AppPreferences,
    PreferenceSnapshot,
    SecretMaterial,
    SecretRef,
)
from meeting_memory.types.configuration_editing import (
    CapabilityConfiguration,
    ConfigurationChange,
    ConfigurationEditId,
    ConfigurationSaveOutcome,
    ConfigurationSaveState,
    SecretAvailability,
)
from meeting_memory.types.configuration_resolution import SettingSource
from meeting_memory.types.runtime_layout import RuntimeLayout


class PreferenceEditorStore(Protocol):
    def load_snapshot(self) -> PreferenceSnapshot:
        raise NotImplementedError

    def compare_and_swap(
        self, expected: PreferenceSnapshot, replacement: AppPreferences
    ) -> PreferenceSnapshot:
        raise NotImplementedError


class SecretEditorStore(Protocol):
    def read(self, ref: SecretRef) -> SecretMaterial | None:
        raise NotImplementedError

    def write_new(self, bundle) -> SecretRef:
        raise NotImplementedError

    def delete(self, ref: SecretRef) -> None:
        raise NotImplementedError


class ConfigurationEditingError(RuntimeError):
    """Sanitized form-load failure safe for a typed UI event."""


@dataclass(frozen=True, slots=True)
class _EditBinding:
    snapshot: PreferenceSnapshot
    capability: Capability
    secret_availability: SecretAvailability
    process_present: bool
    process_reenables: bool
    legacy_reenables: bool


class CapabilityConfigurationService:
    """Open and consume one exact app-owned capability edit."""

    def __init__(
        self,
        *,
        preference_store: PreferenceEditorStore | None = None,
        secret_store: SecretEditorStore | None = None,
        env_path: str | Path | None = ".env",
        process_environment: Mapping[str, str] | None = None,
        id_factory: Callable[[], str] | None = None,
        runtime_layout: RuntimeLayout | None = None,
    ) -> None:
        self._preferences = (
            preference_store if preference_store is not None else PreferenceStore.default()
        )
        self._secrets = secret_store if secret_store is not None else KeychainSecretStore()
        self._env_path = editing_legacy_source(env_path, runtime_layout)
        self._process = process_environment
        self._id_factory = id_factory if id_factory is not None else lambda: uuid.uuid4().hex
        self._lock = threading.Lock()
        self._bindings: dict[ConfigurationEditId, _EditBinding] = {}

    def open(self, capability: Capability) -> CapabilityConfiguration:
        try:
            snapshot = self._preferences.load_snapshot()
            if not isinstance(snapshot, PreferenceSnapshot):
                raise TypeError("invalid preference snapshot")
            process = dict(os.environ if self._process is None else self._process)
            legacy, _legacy_failed = load_legacy_environment(self._env_path)
            availability, materials = self._secret_state(capability, snapshot)
            resolved = resolve_configuration(
                process_environment=process,
                preferences=snapshot.preferences,
                app_secrets=materials,
                legacy_environment=legacy,
            )
            provenance = tuple(
                item
                for item in resolved.provenance
                if any(definition.key is item.key for definition in definitions_for(capability))
            )
            capability_resolution = resolved.capability_for(capability)
            process_present = any(item.source is SettingSource.PROCESS_ENV for item in provenance)
            process_reenables = (
                capability is not Capability.RECORDING_CORE
                and capability_resolution.process_override
            )
            legacy_active = capability_resolution.enabled and any(
                item.source is SettingSource.LEGACY_ENV and item.active for item in provenance
            )
            legacy_will_reenable = legacy_reenables(
                capability,
                snapshot,
                process,
                legacy,
                materials,
            )
            edit_id = ConfigurationEditId(self._id_factory())
            binding = _EditBinding(
                snapshot,
                capability,
                availability,
                process_present,
                process_reenables,
                legacy_will_reenable,
            )
            with self._lock:
                self._bindings.clear()
                self._bindings[edit_id] = binding
            preference = (
                None
                if capability is Capability.RECORDING_CORE
                else snapshot.preferences.enabled_for(capability)
            )
            return CapabilityConfiguration(
                edit_id,
                capability,
                preference,
                editable_fields(capability, snapshot.preferences),
                availability,
                legacy_active,
                process_present,
                process_reenables,
                legacy_will_reenable,
            )
        except ConfigurationEditingError:
            raise
        except Exception:
            raise ConfigurationEditingError(
                "App-owned configuration could not be loaded."
            ) from None

    def save(self, change: ConfigurationChange) -> ConfigurationSaveOutcome:
        if not isinstance(change, ConfigurationChange):
            raise ConfigurationEditingError("Configuration change was rejected.")
        binding = self._consume(change)
        if binding is None:
            return configuration_outcome(ConfigurationSaveState.REJECTED, change.capability)
        flags = {
            "process_present": binding.process_present,
            "process_reenables": binding.process_reenables,
            "legacy_reenables": binding.legacy_reenables and change.enabled is None,
        }
        if (
            change.enabled is None
            and binding.snapshot.preferences.enabled_for(change.capability) is False
            and not change.disclosure_confirmed
        ):
            return configuration_outcome(
                ConfigurationSaveState.REJECTED, change.capability, **flags
            )
        can_retain = binding.secret_availability is SecretAvailability.AVAILABLE
        if not valid_change(change, can_retain_secret=can_retain):
            return configuration_outcome(
                ConfigurationSaveState.REJECTED,
                change.capability,
                **flags,
            )
        current = binding.snapshot.preferences
        provisional = replacement_preferences(current, change, None)
        if provisional == current and change.secret is None:
            if change.enabled is False and binding.process_reenables:
                return configuration_outcome(
                    ConfigurationSaveState.SESSION_PAUSED,
                    change.capability,
                    pause=True,
                    **flags,
                )
            return configuration_outcome(
                ConfigurationSaveState.UNCHANGED,
                change.capability,
                **flags,
            )
        try:
            if self._preferences.load_snapshot() != binding.snapshot:
                return configuration_outcome(
                    ConfigurationSaveState.PREFERENCES_CONFLICT,
                    change.capability,
                    **flags,
                )
        except Exception:
            return configuration_outcome(
                ConfigurationSaveState.FAILED,
                change.capability,
                **flags,
            )
        new_ref = write_new_secret(self._secrets, change, binding.snapshot)
        if isinstance(new_ref, ConfigurationSaveState):
            return configuration_outcome(
                new_ref,
                change.capability,
                **flags,
            )
        replacement = replacement_preferences(current, change, new_ref)
        intended = snapshot_for_preferences(replacement)
        state = save_replacement(
            self._preferences,
            self._secrets,
            binding.snapshot,
            replacement,
            intended,
            new_ref,
        )
        if state is ConfigurationSaveState.SAVED and new_ref is not None:
            old_ref = binding.snapshot.preferences.secret_ref_for(new_ref.secret_id)
            if old_ref is not None and old_ref != new_ref:
                try:
                    self._secrets.delete(old_ref)
                except Exception:
                    state = ConfigurationSaveState.SAVED_CLEANUP_FAILED
        activated = state in {
            ConfigurationSaveState.SAVED,
            ConfigurationSaveState.SAVED_CLEANUP_FAILED,
            ConfigurationSaveState.DURABILITY_UNCERTAIN,
            ConfigurationSaveState.ACTIVATION_UNCERTAIN,
        }
        return configuration_outcome(
            state,
            change.capability,
            restart=activated and change.enabled is not False,
            pause=activated and change.capability is not Capability.RECORDING_CORE,
            **flags,
        )

    def _consume(self, change: ConfigurationChange) -> _EditBinding | None:
        if not isinstance(change, ConfigurationChange):
            return None
        with self._lock:
            binding = self._bindings.pop(change.edit_id, None)
        if binding is None or binding.capability is not change.capability:
            return None
        return binding

    def _secret_state(
        self,
        capability: Capability,
        snapshot: PreferenceSnapshot,
    ) -> tuple[SecretAvailability, tuple[SecretMaterial, ...]]:
        secret_id = secret_id_for_capability(capability)
        if secret_id is None:
            return SecretAvailability.NONE, ()
        ref = snapshot.preferences.secret_ref_for(secret_id)
        if ref is None:
            return SecretAvailability.UNAVAILABLE, ()
        materials, failed = read_secret_materials((ref,), self._secrets.read)
        if failed or len(materials) != 1 or materials[0].ref != ref:
            return SecretAvailability.UNAVAILABLE, ()
        return SecretAvailability.AVAILABLE, materials

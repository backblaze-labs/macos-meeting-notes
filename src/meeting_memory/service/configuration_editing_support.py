"""Pure validation and merge helpers for explicit configuration edits."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from meeting_memory.config.resolution import resolve_configuration
from meeting_memory.config.schema import definitions_for, required_keys
from meeting_memory.config.settings import Settings
from meeting_memory.config.validation import configured_value, valid_required_setting
from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration import (
    AppPreferences,
    CapabilityPreference,
    PreferenceKey,
    PreferenceSnapshot,
    PreferenceValue,
    SecretId,
    SecretMaterial,
    SecretRef,
    SettingKey,
)
from meeting_memory.types.configuration_editing import (
    ConfigurationChange,
    ConfigurationField,
    ConfigurationValue,
)
from meeting_memory.types.configuration_resolution import SettingSource

_CAPABILITY_SECRET = {
    Capability.TRANSCRIPTION: SecretId.TRANSCRIPTION,
    Capability.BACKUP: SecretId.BACKUP,
    Capability.NOTES: SecretId.NOTES,
}


def editable_fields(
    capability: Capability,
    preferences: AppPreferences,
) -> tuple[ConfigurationField, ...]:
    results: list[ConfigurationField] = []
    for definition in definitions_for(capability):
        if definition.secret:
            continue
        key = PreferenceKey(definition.key.value)
        value = preferences.value_for(key)
        if value is None:
            value = _default_text(definition.default)
        results.append(ConfigurationField(definition.key, ConfigurationValue(value)))
    return tuple(results)


def valid_change(change: ConfigurationChange, *, can_retain_secret: bool) -> bool:
    if change.capability is Capability.RECORDING_CORE:
        return all(_valid_field(field) for field in change.fields)
    if change.enabled in {False, None}:
        return change.secret is None
    if not all(_valid_field(field) for field in change.fields):
        return False
    secret_id = secret_id_for_capability(change.capability)
    return secret_id is None or change.secret is not None or can_retain_secret


def replacement_preferences(
    current: AppPreferences,
    change: ConfigurationChange,
    new_ref: SecretRef | None,
) -> AppPreferences:
    values = current.values
    if change.capability is Capability.RECORDING_CORE or change.enabled is True:
        changed_keys = {PreferenceKey(field.key.value) for field in change.fields}
        values = tuple(item for item in current.values if item.key not in changed_keys)
        values += tuple(
            PreferenceValue(PreferenceKey(field.key.value), field.value.value)
            for field in change.fields
        )
    capabilities = current.capabilities
    if change.capability is not Capability.RECORDING_CORE:
        capabilities = tuple(
            item for item in capabilities if item.capability is not change.capability
        ) + (CapabilityPreference(change.capability, change.enabled),)
    refs = current.secret_refs
    if new_ref is not None:
        refs = tuple(item for item in refs if item.secret_id is not new_ref.secret_id) + (new_ref,)
    return AppPreferences(values, capabilities, refs)


def secret_id_for_capability(capability: Capability) -> SecretId | None:
    return _CAPABILITY_SECRET.get(capability)


def legacy_reenables(
    capability: Capability,
    snapshot: PreferenceSnapshot,
    process: Mapping[str, str],
    legacy: Mapping[str, str],
    materials: tuple[SecretMaterial, ...],
) -> bool:
    if (
        capability is Capability.RECORDING_CORE
        or snapshot.preferences.enabled_for(capability) is not False
    ):
        return False
    preferences = snapshot.preferences
    compatibility = AppPreferences(
        preferences.values,
        tuple(item for item in preferences.capabilities if item.capability is not capability),
        preferences.secret_refs,
    )
    resolved = resolve_configuration(
        process_environment=process,
        preferences=compatibility,
        app_secrets=materials,
        legacy_environment=legacy,
    )
    resolution = resolved.capability_for(capability)
    keys = {definition.key for definition in definitions_for(capability)}
    required_valid = all(
        valid_required_setting(key, str(resolved.value_for(key) or ""))
        for key in required_keys(capability)
    )
    return (
        resolution.enabled
        and required_valid
        and any(
            item.active and item.source is SettingSource.LEGACY_ENV and item.key in keys
            for item in resolved.provenance
        )
    )


def _valid_field(field: ConfigurationField) -> bool:
    key = field.key
    value = field.value.value
    if not configured_value(value) or "\x00" in value:
        return False
    if not valid_required_setting(key, value):
        return False
    try:
        if key is SettingKey.MAX_RECORDING_MINUTES:
            return int(value) > 0
        if key is SettingKey.NOTIFY_MINUTES_BEFORE:
            return int(value) >= 0
        if key is SettingKey.CALENDAR_POLL_INTERVAL:
            return int(value) > 0
        if key is SettingKey.KNOWN_SPEAKERS:
            Settings.parse_known_speakers(value)
        if key in {
            SettingKey.MEETINGS_DIR,
            SettingKey.GOOGLE_CALENDAR_CREDENTIALS_FILE,
            SettingKey.SUMMARY_PROMPT_FILE,
        }:
            Path(value)
    except (TypeError, ValueError):
        return False
    return True


def _default_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, tuple):
        return json.dumps(
            [{"name": item.name, "matches": list(item.matches)} for item in value],
            separators=(",", ":"),
        )
    return str(value)

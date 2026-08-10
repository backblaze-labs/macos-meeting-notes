"""Pure resolver for progressive configuration precedence."""

from __future__ import annotations

from collections.abc import Mapping

from meeting_memory.config.schema import (
    SETTING_DEFINITIONS,
    required_keys,
)
from meeting_memory.config.validation import configured_value, valid_required_setting
from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration import (
    AppPreferences,
    PreferenceKey,
    SecretId,
    SecretMaterial,
    SettingKey,
)
from meeting_memory.types.configuration_resolution import (
    CapabilityResolution,
    ConfigurationResolution,
    ResolvedSetting,
    SettingProvenance,
    SettingSource,
)

SOURCE_PRIORITY = (
    SettingSource.PROCESS_ENV,
    SettingSource.APP_KEYCHAIN,
    SettingSource.APP_PREFERENCE,
    SettingSource.LEGACY_ENV,
    SettingSource.DEFAULT,
)


def resolve_configuration(
    *,
    process_environment: Mapping[str, str],
    preferences: AppPreferences | None,
    app_secrets: tuple[SecretMaterial, ...],
    legacy_environment: Mapping[str, str],
) -> ConfigurationResolution:
    """Resolve sources without filesystem, Keychain, provider, or runtime side effects."""

    process = _recognized_values(process_environment)
    legacy = _recognized_values(legacy_environment)
    available = preferences is not None
    resolved_preferences = preferences or AppPreferences()
    secret_values = _active_secret_values(resolved_preferences, app_secrets)
    settings = tuple(
        _resolve_setting(
            definition,
            process,
            resolved_preferences,
            secret_values,
            legacy,
        )
        for definition in SETTING_DEFINITIONS
    )
    capabilities = tuple(
        _resolve_capability(
            capability,
            process,
            resolved_preferences,
            settings,
            secret_values,
            preferences_available=available,
        )
        for capability in Capability
    )
    active = {item.capability: item for item in capabilities}
    final_settings = tuple(
        ResolvedSetting(
            SettingProvenance(
                item.provenance.key,
                item.provenance.source,
                active=active[_capability_for(item.provenance.key)].enabled,
            ),
            item.value,
        )
        for item in settings
    )
    return ConfigurationResolution(final_settings, capabilities)


def _resolve_setting(definition, process, preferences, secrets, legacy) -> ResolvedSetting:
    key = definition.key
    if key in process:
        value, source = process[key], SettingSource.PROCESS_ENV
    elif definition.secret and key in secrets:
        value, source = secrets[key], SettingSource.APP_KEYCHAIN
    elif definition.secret and _requires_app_secret(definition, preferences):
        value, source = None, SettingSource.APP_KEYCHAIN
    elif (
        not definition.secret
        and (value := _app_preference_value(definition, preferences)) is not None
    ):
        source = SettingSource.APP_PREFERENCE
    elif (
        not definition.secret
        and definition.required_to_enable
        and preferences.enabled_for(definition.capability) is True
    ):
        value, source = None, SettingSource.APP_PREFERENCE
    elif key in legacy:
        value, source = legacy[key], SettingSource.LEGACY_ENV
    else:
        value, source = definition.default, SettingSource.DEFAULT
    return ResolvedSetting(SettingProvenance(key, source), value)


def _resolve_capability(
    capability: Capability,
    process: Mapping[SettingKey, str],
    preferences: AppPreferences,
    settings: tuple[ResolvedSetting, ...],
    secret_values: Mapping[SettingKey, str],
    *,
    preferences_available: bool,
) -> CapabilityResolution:
    if capability is Capability.RECORDING_CORE:
        return CapabilityResolution(capability, None, True, SettingSource.DEFAULT)

    preference = preferences.enabled_for(capability)
    required = required_keys(capability)
    process_override = bool(required) and all(
        key in process and valid_required_setting(key, process[key]) for key in required
    )
    if process_override:
        return CapabilityResolution(
            capability,
            preference,
            True,
            SettingSource.PROCESS_ENV,
            process_override=True,
            configuration_error=not preferences_available,
        )
    if not preferences_available:
        return CapabilityResolution(
            capability,
            None,
            False,
            SettingSource.APP_PREFERENCE,
            configuration_error=True,
        )
    if preference is False:
        return CapabilityResolution(
            capability,
            preference,
            False,
            SettingSource.APP_PREFERENCE,
        )
    if preference is True:
        app_required = tuple(
            (key, _app_required_value(key, process, preferences, secret_values)) for key in required
        )
        app_ready = all(
            value is not None and valid_required_setting(key, value) for key, value in app_required
        )
        resolved_required = [item for item in settings if item.provenance.key in required]
        resolved_ready = bool(resolved_required) and all(
            valid_required_setting(item.provenance.key, item.value) for item in resolved_required
        )
        enabled = app_ready and resolved_ready
        return CapabilityResolution(
            capability,
            True,
            enabled,
            SettingSource.APP_PREFERENCE,
            configuration_error=not enabled,
        )

    selected = [item for item in settings if item.provenance.key in required]
    enabled = bool(selected) and all(configured_value(item.value) for item in selected)
    return CapabilityResolution(
        capability,
        None,
        enabled,
        _highest_source(item for item in selected if configured_value(item.value)),
    )


def _active_secret_values(
    preferences: AppPreferences,
    materials: tuple[SecretMaterial, ...],
) -> dict[SettingKey, str]:
    values: dict[SettingKey, str] = {}
    seen = set()
    for material in materials:
        if material.ref.secret_id in seen:
            raise ValueError("secret material providers must be unique")
        seen.add(material.ref.secret_id)
        capability = _secret_capability(material.ref.secret_id)
        if preferences.enabled_for(capability) is not True:
            continue
        if preferences.secret_ref_for(material.ref.secret_id) != material.ref:
            continue
        values.update((item.key, item.value) for item in material.bundle.values)
    return values


def _recognized_values(values: Mapping[str, str]) -> dict[SettingKey, str]:
    return {key: str(values[key.value]) for key in SettingKey if key.value in values}


def has_invalid_process_required(
    capability: Capability,
    resolution: ConfigurationResolution,
) -> bool:
    """Whether a selected required process value is present but invalid."""

    required = set(required_keys(capability))
    return any(
        item.provenance.key in required
        and item.provenance.source is SettingSource.PROCESS_ENV
        and not valid_required_setting(item.provenance.key, item.value)
        for item in resolution.settings
    )


def _highest_source(settings) -> SettingSource:
    sources = {item.provenance.source for item in settings}
    return next((source for source in SOURCE_PRIORITY if source in sources), SettingSource.DEFAULT)


def _capability_for(key: SettingKey) -> Capability:
    return next(
        definition.capability for definition in SETTING_DEFINITIONS if definition.key is key
    )


def _requires_app_secret(definition, preferences: AppPreferences) -> bool:
    return definition.secret and preferences.enabled_for(definition.capability) is True


def _app_preference_value(definition, preferences: AppPreferences) -> str | None:
    if (
        definition.capability is not Capability.RECORDING_CORE
        and preferences.enabled_for(definition.capability) is not True
    ):
        return None
    return preferences.value_for(PreferenceKey(definition.key.value))


def _app_required_value(
    key: SettingKey,
    process: Mapping[SettingKey, str],
    preferences: AppPreferences,
    secrets: Mapping[SettingKey, str],
) -> object:
    if key in process:
        return process[key]
    if key in secrets:
        return secrets[key]
    try:
        return preferences.value_for(PreferenceKey(key.value))
    except ValueError:
        return None


def _secret_capability(secret_id: SecretId) -> Capability:
    return {
        SecretId.TRANSCRIPTION: Capability.TRANSCRIPTION,
        SecretId.BACKUP: Capability.BACKUP,
        SecretId.NOTES: Capability.NOTES,
    }[secret_id]

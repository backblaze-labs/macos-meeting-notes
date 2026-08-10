"""Scoped, side-effect-bounded composition of effective app configuration."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from meeting_memory.config.resolution import (
    has_invalid_process_required,
    resolve_configuration,
)
from meeting_memory.config.runtime import RuntimeSettings
from meeting_memory.config.schema import SETTING_DEFINITIONS, secret_id_for
from meeting_memory.service.configuration_issues import configuration_issues
from meeting_memory.service.configuration_loaded import LoadedConfiguration
from meeting_memory.service.configuration_sources import (
    PreferenceReader,
    SecretReader,
    load_legacy_environment,
    load_preferences,
    read_secret_materials,
)
from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration import (
    AppPreferences,
    SecretId,
    SecretRef,
    SettingKey,
    secret_setting_keys,
)
from meeting_memory.types.configuration_resolution import (
    ConfigurationIssue,
    ConfigurationResolution,
    ConfigurationUse,
    ScopedConfigurationResolution,
    SettingSource,
)

_ALL_KEYS = tuple(SettingKey)
_ALL_CAPABILITIES = tuple(Capability)
_USE_KEYS = {
    ConfigurationUse.RUNTIME: _ALL_KEYS,
    ConfigurationUse.READINESS: _ALL_KEYS,
    ConfigurationUse.AUTH: (
        SettingKey.GOOGLE_CALENDAR_CREDENTIALS_FILE,
        SettingKey.GOOGLE_CALENDAR_ID,
        SettingKey.KNOWN_SPEAKERS,
    ),
    ConfigurationUse.SEARCH: (SettingKey.MEETINGS_DIR,),
    ConfigurationUse.SUMMARIZE: (
        SettingKey.MEETINGS_DIR,
        SettingKey.ANTHROPIC_API_KEY,
        SettingKey.ANTHROPIC_MODEL,
        SettingKey.SUMMARY_PROMPT_FILE,
    ),
}
_USE_CAPABILITIES = {
    ConfigurationUse.RUNTIME: _ALL_CAPABILITIES,
    ConfigurationUse.READINESS: _ALL_CAPABILITIES,
    ConfigurationUse.AUTH: (Capability.CALENDAR,),
    ConfigurationUse.SEARCH: (Capability.RECORDING_CORE,),
    ConfigurationUse.SUMMARIZE: (Capability.RECORDING_CORE, Capability.NOTES),
}


class ConfigurationLoadError(RuntimeError):
    """A sanitized composition failure safe for command/UI boundaries."""


def load_configuration(
    use: ConfigurationUse,
    *,
    env_file: str | Path | None = ".env",
    process_environment: Mapping[str, str] | None = None,
    preference_reader: PreferenceReader | None = None,
    secret_reader: SecretReader | None = None,
) -> LoadedConfiguration:
    """Load exactly one fixed scope without provider/network/write operations."""

    if not isinstance(use, ConfigurationUse):
        raise ValueError("configuration use must be a typed fixed scope")
    process = dict(os.environ if process_environment is None else process_environment)
    legacy, legacy_failed = load_legacy_environment(env_file)
    preferences, preferences_failed = load_preferences(preference_reader)
    preliminary = resolve_configuration(
        process_environment=process,
        preferences=preferences,
        app_secrets=(),
        legacy_environment=legacy,
    )
    refs = _scoped_secret_refs(use, preferences, preliminary)
    materials, failed_secrets = read_secret_materials(
        refs,
        secret_reader,
    )
    resolved = resolve_configuration(
        process_environment=process,
        preferences=preferences,
        app_secrets=materials,
        legacy_environment=legacy,
    )
    issues = configuration_issues(
        _USE_CAPABILITIES[use],
        resolved,
        preferences,
        preferences_failed=preferences_failed,
        legacy_failed=legacy_failed,
        failed_secrets=failed_secrets,
    )
    if any(issue.capability is Capability.RECORDING_CORE and issue.blocking for issue in issues):
        raise ConfigurationLoadError("Recording Core configuration could not be loaded.")
    settings = _materialize_settings(use, resolved, issues)
    keys = _USE_KEYS[use]
    capabilities = _USE_CAPABILITIES[use]
    scoped = ScopedConfigurationResolution(
        tuple(item for item in resolved.settings if item.provenance.key in keys),
        tuple(item for item in resolved.capabilities if item.capability in capabilities),
    )
    return LoadedConfiguration(use, settings, scoped, issues)


def _scoped_secret_refs(
    use: ConfigurationUse,
    preferences: AppPreferences | None,
    preliminary: ConfigurationResolution,
) -> tuple[SecretRef, ...]:
    if preferences is None:
        return ()
    keys = set(_USE_KEYS[use])
    refs: list[SecretRef] = []
    for secret_id in SecretId:
        capability = _secret_capability(secret_id)
        if capability not in _USE_CAPABILITIES[use]:
            continue
        if not any(secret_id_for(key) is secret_id for key in keys):
            continue
        if preferences.enabled_for(capability) is not True:
            continue
        if has_invalid_process_required(capability, preliminary):
            continue
        if preliminary.capability_for(capability).process_override:
            continue
        if all(
            next(item.source for item in preliminary.provenance if item.key is key)
            is SettingSource.PROCESS_ENV
            for key in secret_setting_keys(secret_id)
        ):
            continue
        if (ref := preferences.secret_ref_for(secret_id)) is not None:
            refs.append(ref)
    return tuple(refs)


def _materialize_settings(
    use: ConfigurationUse,
    resolution: ConfigurationResolution,
    issues: tuple[ConfigurationIssue, ...],
) -> RuntimeSettings:
    keys = set(_USE_KEYS[use])
    values: dict[str, object] = {}
    for definition in SETTING_DEFINITIONS:
        enabled = resolution.capability_for(definition.capability).enabled and not any(
            item.capability is definition.capability and item.blocking for item in issues
        )
        value = (
            resolution.value_for(definition.key)
            if definition.key in keys and enabled
            else definition.default
        )
        values[definition.key.value.lower()] = value
    try:
        return RuntimeSettings(_env_file=None, **values)
    except Exception:
        raise ConfigurationLoadError("Effective configuration could not be loaded.") from None


def _capability_for(key: SettingKey) -> Capability:
    return next(item.capability for item in SETTING_DEFINITIONS if item.key is key)


def _secret_capability(secret_id: SecretId) -> Capability:
    return _capability_for(next(key for key in SettingKey if secret_id_for(key) is secret_id))

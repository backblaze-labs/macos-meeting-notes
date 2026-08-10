"""Sanitized capability-local issues derived from composed configuration."""

from __future__ import annotations

from meeting_memory.config.resolution import has_invalid_process_required
from meeting_memory.config.schema import SETTING_DEFINITIONS, secret_id_for
from meeting_memory.config.validation import valid_b2_endpoint
from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration import AppPreferences, SecretId, SettingKey
from meeting_memory.types.configuration_resolution import (
    ConfigurationIssue,
    ConfigurationIssueCode,
    ConfigurationResolution,
)


def configuration_issues(
    capabilities: tuple[Capability, ...],
    resolution: ConfigurationResolution,
    preferences: AppPreferences | None,
    *,
    preferences_failed: bool,
    legacy_failed: bool,
    failed_secrets: frozenset[SecretId],
) -> tuple[ConfigurationIssue, ...]:
    """Describe only safe, actionable local composition failures."""

    issues: list[ConfigurationIssue] = []
    for capability in capabilities:
        resolved = resolution.capability_for(capability)
        if preferences_failed and capability is not Capability.RECORDING_CORE:
            issues.append(
                _issue(
                    capability,
                    ConfigurationIssueCode.PREFERENCES_UNAVAILABLE,
                    not resolved.process_override,
                )
            )
        if legacy_failed and (
            capability is Capability.RECORDING_CORE or resolved.preference is None
        ):
            blocking = capability is not Capability.RECORDING_CORE and not resolved.enabled
            issues.append(
                _issue(
                    capability,
                    ConfigurationIssueCode.LEGACY_ENV_UNAVAILABLE,
                    blocking,
                )
            )
        secret_id = _capability_secret(capability)
        if _invalid_selected_process_value(
            capability,
            resolved.preference,
            resolution,
            preferences_failed,
        ):
            issues.append(_process_issue(capability))
        elif secret_id in failed_secrets:
            issues.append(_issue(capability, ConfigurationIssueCode.SECRET_UNAVAILABLE, True))
        elif _invalid_app_configuration(
            capability,
            resolved.configuration_error,
            resolved.process_override,
            preferences,
            preferences_failed,
        ):
            issues.append(
                _issue(
                    capability,
                    ConfigurationIssueCode.APP_CONFIGURATION_INVALID,
                    True,
                )
            )
        elif _invalid_effective_configuration(capability, resolved.enabled, resolution):
            issues.append(
                _issue(
                    capability,
                    ConfigurationIssueCode.EFFECTIVE_CONFIGURATION_INVALID,
                    True,
                )
            )
    return tuple(issues)


def _invalid_app_configuration(
    capability: Capability,
    configuration_error: bool,
    process_override: bool,
    preferences: AppPreferences | None,
    preferences_failed: bool,
) -> bool:
    return (
        not preferences_failed
        and capability is not Capability.RECORDING_CORE
        and preferences is not None
        and preferences.enabled_for(capability) is True
        and configuration_error
        and not process_override
    )


def _issue(
    capability: Capability,
    code: ConfigurationIssueCode,
    blocking: bool,
) -> ConfigurationIssue:
    messages = {
        ConfigurationIssueCode.PREFERENCES_UNAVAILABLE: (
            "App preferences could not be loaded.",
            "Repair app preferences or provide a complete process-environment override.",
        ),
        ConfigurationIssueCode.LEGACY_ENV_UNAVAILABLE: (
            "The legacy environment file could not be read.",
            "Repair the legacy .env file or configure this capability from another source.",
        ),
        ConfigurationIssueCode.SECRET_UNAVAILABLE: (
            "The app credential could not be read from Keychain.",
            "Unlock Keychain or reconfigure this capability, then retry.",
        ),
        ConfigurationIssueCode.APP_CONFIGURATION_INVALID: (
            "App-owned configuration is incomplete or invalid.",
            "Review this capability's app-owned settings, then retry.",
        ),
        ConfigurationIssueCode.EFFECTIVE_CONFIGURATION_INVALID: (
            "Effective configuration is invalid for this capability.",
            "Fix the selected configuration source, then retry.",
        ),
    }
    summary, action = messages[code]
    return ConfigurationIssue(capability, code, blocking, summary, action)


def _process_issue(capability: Capability) -> ConfigurationIssue:
    return ConfigurationIssue(
        capability,
        ConfigurationIssueCode.EFFECTIVE_CONFIGURATION_INVALID,
        True,
        "Process environment override requires attention.",
        "Fix or remove the process environment override, then retry.",
    )


def _capability_secret(capability: Capability) -> SecretId | None:
    return next(
        (
            secret_id_for(item.key)
            for item in SETTING_DEFINITIONS
            if item.capability is capability and secret_id_for(item.key) is not None
        ),
        None,
    )


def _invalid_effective_configuration(
    capability: Capability,
    enabled: bool,
    resolution: ConfigurationResolution,
) -> bool:
    if not enabled:
        return False
    if capability is Capability.RECORDING_CORE:
        meetings_dir = resolution.value_for(SettingKey.MEETINGS_DIR)
        return not str(meetings_dir or "").strip()
    if capability is not Capability.BACKUP:
        return False
    endpoint = resolution.value_for(SettingKey.B2_ENDPOINT)
    return not valid_b2_endpoint(endpoint)


def _invalid_selected_process_value(
    capability: Capability,
    preference: bool | None,
    resolution: ConfigurationResolution,
    preferences_failed: bool,
) -> bool:
    if capability is Capability.RECORDING_CORE or preference is False or preferences_failed:
        return False
    return has_invalid_process_required(capability, resolution)

"""Pure precedence, opt-in, and provenance tests."""

from __future__ import annotations

import json
from dataclasses import asdict

from meeting_memory.config.resolution import resolve_configuration
from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration import (
    AppPreferences,
    CapabilityPreference,
    PreferenceKey,
    PreferenceValue,
    SecretBundle,
    SecretId,
    SecretMaterial,
    SecretRef,
    SecretValue,
    SettingKey,
)
from meeting_memory.types.configuration_resolution import SettingSource


def test_exact_per_field_precedence_and_value_free_provenance() -> None:
    secret = "app-secret-sentinel"
    preferences, material = _transcription_preferences(secret, enabled=True)
    preferences = AppPreferences(
        values=(PreferenceValue(PreferenceKey.MAX_RECORDING_MINUTES, "90"),),
        capabilities=preferences.capabilities,
        secret_refs=preferences.secret_refs,
    )
    result = _resolve(
        process={"MEETINGS_DIR": "/process/meetings"},
        preferences=preferences,
        materials=(material,),
        legacy={
            "MEETINGS_DIR": "/legacy/meetings",
            "MAX_RECORDING_MINUTES": "45",
            "ASSEMBLYAI_API_KEY": "legacy-secret",
            "GOOGLE_CALENDAR_ID": "legacy-calendar",
        },
    )

    assert result.value_for(SettingKey.MEETINGS_DIR) == "/process/meetings"
    assert result.value_for(SettingKey.MAX_RECORDING_MINUTES) == "90"
    assert result.value_for(SettingKey.ASSEMBLYAI_API_KEY) == secret
    assert result.value_for(SettingKey.GOOGLE_CALENDAR_ID) == "legacy-calendar"
    assert _source(result, SettingKey.MEETINGS_DIR) is SettingSource.PROCESS_ENV
    assert _source(result, SettingKey.MAX_RECORDING_MINUTES) is SettingSource.APP_PREFERENCE
    assert _source(result, SettingKey.ASSEMBLYAI_API_KEY) is SettingSource.APP_KEYCHAIN
    assert _source(result, SettingKey.GOOGLE_CALENDAR_ID) is SettingSource.LEGACY_ENV
    diagnostic = json.dumps(asdict(result), default=repr)
    assert secret not in repr(result)
    assert secret not in diagnostic


def test_first_present_source_wins_even_when_blank_or_invalid() -> None:
    result = _resolve(
        process={"ASSEMBLYAI_API_KEY": ""},
        legacy={"ASSEMBLYAI_API_KEY": "legacy-secret-sentinel"},
    )

    assert result.value_for(SettingKey.ASSEMBLYAI_API_KEY) == ""
    assert _source(result, SettingKey.ASSEMBLYAI_API_KEY) is SettingSource.PROCESS_ENV
    assert _capability(result, Capability.TRANSCRIPTION).enabled is False


def test_explicit_disable_masks_refs_and_legacy_until_complete_process_override() -> None:
    preferences, material = _backup_preferences(enabled=False)
    legacy = _backup_values("legacy")
    partial = _resolve(
        process={"B2_APPLICATION_KEY_ID": "process-id"},
        preferences=preferences,
        materials=(material,),
        legacy=legacy,
    )

    backup = _capability(partial, Capability.BACKUP)
    assert backup.enabled is False
    assert backup.process_override is False
    assert all(not item.active for item in partial.provenance if item.key.value.startswith("B2_"))
    assert partial.value_for(SettingKey.B2_APPLICATION_KEY) == legacy["B2_APPLICATION_KEY"]

    complete = _resolve(
        process=_backup_values("process"),
        preferences=preferences,
        materials=(material,),
        legacy=legacy,
    )
    backup = _capability(complete, Capability.BACKUP)
    assert backup.enabled is True
    assert backup.process_override is True
    assert all(
        item.source is SettingSource.PROCESS_ENV and item.active
        for item in complete.provenance
        if item.key.value.startswith("B2_")
    )


def test_invalid_complete_process_group_does_not_override_disable() -> None:
    preferences, material = _backup_preferences(enabled=False)
    process = _backup_values("process")
    process["B2_ENDPOINT"] = "http://not-secure.invalid"

    result = _resolve(process=process, preferences=preferences, materials=(material,))

    assert _capability(result, Capability.BACKUP).enabled is False
    assert not any(item.active for item in result.provenance if item.key.value.startswith("B2_"))


def test_malformed_b2_endpoint_fails_closed_without_breaking_core() -> None:
    preferences, material = _backup_preferences(enabled=False)
    process = _backup_values("process")
    process["B2_ENDPOINT"] = "https://["

    result = _resolve(process=process, preferences=preferences, materials=(material,))

    assert _capability(result, Capability.RECORDING_CORE).enabled is True
    backup = _capability(result, Capability.BACKUP)
    assert backup.enabled is False
    assert backup.process_override is False

    app_preferences = AppPreferences(
        values=(
            PreferenceValue(PreferenceKey.B2_ENDPOINT, "https://["),
            PreferenceValue(PreferenceKey.B2_REGION, "region"),
            PreferenceValue(PreferenceKey.B2_BUCKET_NAME, "bucket"),
        ),
        capabilities=(CapabilityPreference(Capability.BACKUP, True),),
        secret_refs=preferences.secret_refs,
    )
    app_result = _resolve(preferences=app_preferences, materials=(material,))
    assert _capability(app_result, Capability.RECORDING_CORE).enabled is True
    assert _capability(app_result, Capability.BACKUP).configuration_error is True


def test_legacy_b2_endpoint_keeps_compatibility_selection_for_readiness() -> None:
    legacy = _backup_values("legacy")
    legacy["B2_ENDPOINT"] = "http://legacy.example.invalid"

    result = _resolve(legacy=legacy)

    assert _capability(result, Capability.BACKUP).enabled is True
    assert _source(result, SettingKey.B2_ENDPOINT) is SettingSource.LEGACY_ENV


def test_enabled_missing_activated_ref_fails_closed_without_legacy_fallback() -> None:
    ref = SecretRef(SecretId.TRANSCRIPTION, "b" * 32)
    preferences = AppPreferences(
        capabilities=(CapabilityPreference(Capability.TRANSCRIPTION, True),),
        secret_refs=(ref,),
    )
    result = _resolve(
        preferences=preferences,
        legacy={"ASSEMBLYAI_API_KEY": "legacy-secret-sentinel"},
    )

    assert result.value_for(SettingKey.ASSEMBLYAI_API_KEY) is None
    assert _source(result, SettingKey.ASSEMBLYAI_API_KEY) is SettingSource.APP_KEYCHAIN
    capability = _capability(result, Capability.TRANSCRIPTION)
    assert capability.enabled is False
    assert capability.configuration_error is True
    assert not _provenance(result, SettingKey.ASSEMBLYAI_API_KEY).active


def test_enabled_backup_requires_app_owned_nonsecret_group_not_legacy_fallback() -> None:
    preferences, material = _backup_preferences(enabled=True)
    result = _resolve(
        preferences=preferences,
        materials=(material,),
        legacy=_backup_values("legacy"),
    )

    backup = _capability(result, Capability.BACKUP)
    assert backup.enabled is False
    assert backup.configuration_error is True
    assert result.value_for(SettingKey.B2_ENDPOINT) is None
    assert _source(result, SettingKey.B2_ENDPOINT) is SettingSource.APP_PREFERENCE


def test_enabled_backup_activates_one_complete_app_owned_destination_and_bundle() -> None:
    preferences, material = _backup_preferences(enabled=True)
    preferences = AppPreferences(
        values=(
            PreferenceValue(PreferenceKey.B2_ENDPOINT, "https://app.example.invalid"),
            PreferenceValue(PreferenceKey.B2_REGION, "app-region"),
            PreferenceValue(PreferenceKey.B2_BUCKET_NAME, "app-bucket"),
        ),
        capabilities=preferences.capabilities,
        secret_refs=preferences.secret_refs,
    )

    result = _resolve(preferences=preferences, materials=(material,))

    backup = _capability(result, Capability.BACKUP)
    assert backup.enabled is True
    assert backup.configuration_error is False
    assert _source(result, SettingKey.B2_APPLICATION_KEY) is SettingSource.APP_KEYCHAIN
    assert _source(result, SettingKey.B2_ENDPOINT) is SettingSource.APP_PREFERENCE


def test_only_exact_process_environment_names_are_recognized() -> None:
    result = _resolve(
        process={"assemblyai_api_key": "lowercase-process-secret"},
        legacy={"ASSEMBLYAI_API_KEY": "legacy-secret"},
    )

    assert result.value_for(SettingKey.ASSEMBLYAI_API_KEY) == "legacy-secret"
    assert _source(result, SettingKey.ASSEMBLYAI_API_KEY) is SettingSource.LEGACY_ENV


def test_orphan_ref_is_inactive_until_explicit_enable() -> None:
    preferences, material = _transcription_preferences("orphan-secret", enabled=None)
    result = _resolve(
        preferences=preferences,
        materials=(material,),
        legacy={"ASSEMBLYAI_API_KEY": "legacy-secret"},
    )

    assert result.value_for(SettingKey.ASSEMBLYAI_API_KEY) == "legacy-secret"
    assert _source(result, SettingKey.ASSEMBLYAI_API_KEY) is SettingSource.LEGACY_ENV


def test_unavailable_preferences_fail_closed_for_optionals_but_not_core() -> None:
    result = _resolve(
        preferences=None,
        legacy={**_backup_values("legacy"), "ASSEMBLYAI_API_KEY": "legacy-key"},
    )

    core = _capability(result, Capability.RECORDING_CORE)
    assert core.enabled is True
    for capability in Capability:
        if capability is Capability.RECORDING_CORE:
            continue
        state = _capability(result, capability)
        assert state.enabled is False
        assert state.configuration_error is True
    assert not _provenance(result, SettingKey.B2_ENDPOINT).active


def _resolve(*, process=None, preferences=AppPreferences(), materials=(), legacy=None):
    return resolve_configuration(
        process_environment=process or {},
        preferences=preferences,
        app_secrets=materials,
        legacy_environment=legacy or {},
    )


def _source(result, key: SettingKey):
    return _provenance(result, key).source


def _provenance(result, key: SettingKey):
    return next(item for item in result.provenance if item.key is key)


def _capability(result, capability: Capability):
    return next(item for item in result.capabilities if item.capability is capability)


def _transcription_preferences(secret: str, *, enabled: bool | None):
    ref = SecretRef(SecretId.TRANSCRIPTION, "a" * 32)
    preferences = AppPreferences(
        capabilities=(CapabilityPreference(Capability.TRANSCRIPTION, enabled),),
        secret_refs=(ref,),
    )
    bundle = SecretBundle(
        SecretId.TRANSCRIPTION,
        (SecretValue(SettingKey.ASSEMBLYAI_API_KEY, secret),),
    )
    return preferences, SecretMaterial(ref, bundle)


def _backup_preferences(*, enabled: bool):
    ref = SecretRef(SecretId.BACKUP, "c" * 32)
    preferences = AppPreferences(
        capabilities=(CapabilityPreference(Capability.BACKUP, enabled),),
        secret_refs=(ref,),
    )
    bundle = SecretBundle(
        SecretId.BACKUP,
        (
            SecretValue(SettingKey.B2_APPLICATION_KEY_ID, "app-id"),
            SecretValue(SettingKey.B2_APPLICATION_KEY, "app-key"),
        ),
    )
    return preferences, SecretMaterial(ref, bundle)


def _backup_values(prefix: str) -> dict[str, str]:
    return {
        "B2_APPLICATION_KEY_ID": f"{prefix}-id",
        "B2_APPLICATION_KEY": f"{prefix}-key",
        "B2_ENDPOINT": f"https://{prefix}.example.invalid",
        "B2_REGION": f"{prefix}-region",
        "B2_BUCKET_NAME": f"{prefix}-bucket",
    }

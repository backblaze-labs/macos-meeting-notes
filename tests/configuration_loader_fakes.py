"""Synthetic Stage 4B preferences and secret materials for tests."""

from __future__ import annotations

from pathlib import Path

from meeting_memory.service.configuration_loader import load_configuration
from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration import (
    AppPreferences,
    CapabilityPreference,
    PreferenceKey,
    PreferenceSnapshot,
    PreferenceValue,
    SecretBundle,
    SecretId,
    SecretMaterial,
    SecretRef,
    SecretValue,
    SettingKey,
)
from meeting_memory.types.configuration_resolution import ConfigurationUse


def load_test_configuration(
    use: ConfigurationUse,
    *,
    env_file=None,
    process=None,
    preferences=AppPreferences(),
    reader=None,
):
    return load_configuration(
        use,
        env_file=env_file,
        process_environment=process or {},
        preference_reader=lambda: PreferenceSnapshot(preferences, None),
        secret_reader=reader,
    )


def provider_preferences(
    secret_id: SecretId,
    *,
    enabled: bool,
    secret: str | None = None,
) -> tuple[AppPreferences, SecretMaterial]:
    capability = {
        SecretId.TRANSCRIPTION: Capability.TRANSCRIPTION,
        SecretId.BACKUP: Capability.BACKUP,
        SecretId.NOTES: Capability.NOTES,
    }[secret_id]
    generation = {
        SecretId.TRANSCRIPTION: "a" * 32,
        SecretId.BACKUP: "b" * 32,
        SecretId.NOTES: "c" * 32,
    }[secret_id]
    ref = SecretRef(secret_id, generation)
    bundle = _bundle(secret_id, secret or f"app-{secret_id.value}-secret")
    return (
        AppPreferences(
            capabilities=(CapabilityPreference(capability, enabled),),
            secret_refs=(ref,),
        ),
        SecretMaterial(ref, bundle),
    )


def all_provider_preferences():
    pairs = [provider_preferences(secret_id, enabled=True) for secret_id in SecretId]
    values = (
        PreferenceValue(PreferenceKey.B2_ENDPOINT, "https://s3.example.invalid"),
        PreferenceValue(PreferenceKey.B2_REGION, "region"),
        PreferenceValue(PreferenceKey.B2_BUCKET_NAME, "bucket"),
    )
    preferences = AppPreferences(
        values=values,
        capabilities=tuple(item for pair in pairs for item in pair[0].capabilities),
        secret_refs=tuple(item for pair in pairs for item in pair[0].secret_refs),
    )
    return preferences, {material.ref.secret_id: material for _, material in pairs}


def source_for(loaded, key: SettingKey):
    return next(item.source for item in loaded.resolution.provenance if item.key is key)


def issue_for(loaded, capability: Capability):
    return next(item for item in loaded.issues if item.capability is capability)


def write_env(tmp_path: Path, values: dict[str, str]) -> Path:
    path = tmp_path / ".env"
    path.write_text("".join(f"{key}={value}\n" for key, value in values.items()))
    return path


def _bundle(secret_id: SecretId, secret: str) -> SecretBundle:
    keys = {
        SecretId.TRANSCRIPTION: (SettingKey.ASSEMBLYAI_API_KEY,),
        SecretId.BACKUP: (
            SettingKey.B2_APPLICATION_KEY_ID,
            SettingKey.B2_APPLICATION_KEY,
        ),
        SecretId.NOTES: (SettingKey.ANTHROPIC_API_KEY,),
    }[secret_id]
    return SecretBundle(secret_id, tuple(SecretValue(key, secret) for key in keys))

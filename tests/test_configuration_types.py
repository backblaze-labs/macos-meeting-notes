"""Typed progressive-configuration boundary tests."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pytest

from meeting_memory.config.secret_payloads import (
    SecretPayloadError,
    decode_secret_bundle,
    encode_secret_bundle,
)
from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration import (
    SECRET_KEYS,
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


def test_preference_key_is_an_exhaustive_nonsecret_allowlist() -> None:
    assert {key.setting_key for key in PreferenceKey} == set(SettingKey) - SECRET_KEYS
    with pytest.raises(ValueError, match="allowlisted"):
        PreferenceValue(SettingKey.ASSEMBLYAI_API_KEY, "must-not-persist")  # type: ignore[arg-type]


def test_app_preferences_accept_only_refs_not_secret_material() -> None:
    ref = SecretRef(SecretId.TRANSCRIPTION, "a" * 32)
    bundle = SecretBundle(
        SecretId.TRANSCRIPTION,
        (SecretValue(SettingKey.ASSEMBLYAI_API_KEY, "secret-sentinel"),),
    )
    material = SecretMaterial(ref, bundle)

    preferences = AppPreferences(secret_refs=(ref,))

    assert preferences.secret_refs == (ref,)
    assert not hasattr(preferences, "secret_material")
    with pytest.raises(TypeError):
        AppPreferences(secret_material=(material,))  # type: ignore[call-arg]


def test_recording_core_cannot_be_disabled_and_generations_are_opaque() -> None:
    with pytest.raises(ValueError, match="cannot be disabled"):
        CapabilityPreference(Capability.RECORDING_CORE, False)
    with pytest.raises(ValueError, match="32 lowercase"):
        SecretRef(SecretId.NOTES, "visible-account")


@pytest.mark.parametrize("enabled", [1, 0, "true"])
def test_capability_preferences_require_exact_boundary_types(enabled: object) -> None:
    with pytest.raises(ValueError, match="bool or None"):
        CapabilityPreference(Capability.BACKUP, enabled)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="typed capability"):
        CapabilityPreference("backup", False)  # type: ignore[arg-type]


def test_secret_boundaries_reject_stringly_typed_ids_and_keys() -> None:
    generation = "a" * 32
    with pytest.raises(ValueError, match="typed provider"):
        SecretRef("notes", generation)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="secret setting keys"):
        SecretValue("ANTHROPIC_API_KEY", "secret")  # type: ignore[arg-type]
    value = SecretValue(SettingKey.ANTHROPIC_API_KEY, "secret")
    with pytest.raises(ValueError, match="typed provider"):
        SecretBundle("notes", (value,))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="typed secret values"):
        SecretBundle(SecretId.NOTES, ("secret",))  # type: ignore[arg-type]


def test_backup_secret_bundle_is_atomic_and_all_representations_are_redacted() -> None:
    key_id = "key-id-secret-sentinel"
    key = "application-key-secret-sentinel"
    bundle = SecretBundle(
        SecretId.BACKUP,
        (
            SecretValue(SettingKey.B2_APPLICATION_KEY_ID, key_id),
            SecretValue(SettingKey.B2_APPLICATION_KEY, key),
        ),
    )

    assert key_id not in repr(bundle)
    assert key not in repr(bundle)
    assert key not in repr(bundle.values)
    with pytest.raises(AttributeError, match="immutable"):
        bundle.values[1]._value = "replacement"  # type: ignore[misc]
    with pytest.raises(TypeError):
        asdict(bundle)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="do not match") as error:
        SecretBundle(
            SecretId.BACKUP,
            (SecretValue(SettingKey.B2_APPLICATION_KEY, key),),
        )
    assert key not in str(error.value)


def test_secret_payload_round_trip_and_errors_never_echo_content() -> None:
    secret = "payload-secret-sentinel"
    bundle = SecretBundle(
        SecretId.NOTES,
        (SecretValue(SettingKey.ANTHROPIC_API_KEY, secret),),
    )

    decoded = decode_secret_bundle(encode_secret_bundle(bundle), expected=SecretId.NOTES)

    assert decoded.value_for(SettingKey.ANTHROPIC_API_KEY) == secret
    with pytest.raises(SecretPayloadError) as error:
        decode_secret_bundle(secret, expected=SecretId.NOTES)
    assert secret not in str(error.value)


@pytest.mark.parametrize(
    "payload",
    [
        '{"schema_version":1,"schema_version":1,"secret_id":"notes","values":{}}',
        '{"schema_version":1,"secret_id":"notes","values":{"ANTHROPIC_API_KEY":"a","ANTHROPIC_API_KEY":"b"}}',
        '{"schema_version":true,"secret_id":"notes","values":{"ANTHROPIC_API_KEY":"a"}}',
        '{"schema_version":1.0,"secret_id":"notes","values":{"ANTHROPIC_API_KEY":"a"}}',
    ],
)
def test_secret_payload_rejects_duplicate_keys_and_noninteger_schema(
    payload: str,
) -> None:
    with pytest.raises(SecretPayloadError):
        decode_secret_bundle(payload, expected=SecretId.NOTES)


def test_preferences_require_unique_typed_entries() -> None:
    value = PreferenceValue(PreferenceKey.MEETINGS_DIR, "~/Meetings")
    with pytest.raises(ValueError, match="unique"):
        AppPreferences(values=(value, value))

    selection = CapabilityPreference(Capability.BACKUP, False)
    with pytest.raises(ValueError, match="unique"):
        AppPreferences(capabilities=(selection, selection))

    with pytest.raises(ValueError, match="schema version"):
        AppPreferences(schema_version=True)


def test_preference_and_snapshot_repr_do_not_disclose_values() -> None:
    path = "/Users/person/private-meetings"
    speakers = '{"Private Person":["private@example.com"]}'
    preferences = AppPreferences(
        values=(
            PreferenceValue(PreferenceKey.MEETINGS_DIR, path),
            PreferenceValue(PreferenceKey.KNOWN_SPEAKERS, speakers),
        ),
    )
    snapshot = PreferenceSnapshot(preferences, "a" * 64)

    assert path not in repr(preferences)
    assert speakers not in repr(preferences)
    assert path not in repr(snapshot)
    assert speakers not in repr(snapshot)


def test_phase4_composition_wiring_stays_behind_service_loader() -> None:
    source_root = Path(__file__).resolve().parents[1] / "src" / "meeting_memory"
    active_entrypoints = (
        "__main__.py",
        "config/runtime.py",
        "service/readiness.py",
        "service/readiness_integrations.py",
        "ui/runtime_app.py",
        "ui/tray.py",
    )
    composition_modules = ("config.resolution", "preference_store", "secret_store")
    violations = [
        f"{relative} bypasses composed loader for {module}"
        for relative in active_entrypoints
        for module in composition_modules
        if module in (source_root / relative).read_text(encoding="utf-8")
    ]

    assert violations == []
    loader = (source_root / "service/configuration_loader.py").read_text(encoding="utf-8")
    assert "resolve_configuration" in loader
    assert "load_preferences" in loader
    assert "read_secret_materials" in loader

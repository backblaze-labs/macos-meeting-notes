"""Exact-reference invariants for bounded generic Keychain composition reads."""

from __future__ import annotations

from configuration_loader_fakes import (
    issue_for,
    load_test_configuration,
    provider_preferences,
)

from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration import (
    AppPreferences,
    PreferenceKey,
    PreferenceValue,
    SecretId,
    SecretMaterial,
    SecretRef,
)
from meeting_memory.types.configuration_resolution import (
    ConfigurationIssueCode,
    ConfigurationUse,
)


def test_mismatched_secret_material_reference_fails_only_its_capability() -> None:
    preferences, material = provider_preferences(
        SecretId.TRANSCRIPTION,
        enabled=True,
        secret="mismatch-secret-sentinel",
    )
    mismatched = SecretMaterial(
        SecretRef(SecretId.TRANSCRIPTION, "d" * 32),
        material.bundle,
    )

    loaded = load_test_configuration(
        ConfigurationUse.RUNTIME,
        preferences=preferences,
        reader=lambda _ref: mismatched,
    )

    assert loaded.meetings_dir_path
    assert loaded.transcription is None
    issue = issue_for(loaded, Capability.TRANSCRIPTION)
    assert issue.code is ConfigurationIssueCode.SECRET_UNAVAILABLE
    assert issue.blocking is True
    assert "mismatch-secret-sentinel" not in repr(loaded)


def test_complete_process_secret_pair_skips_unneeded_b2_keychain_bundle() -> None:
    preferences, material = _backup_preferences()
    reads: list[SecretRef] = []

    loaded = load_test_configuration(
        ConfigurationUse.RUNTIME,
        preferences=preferences,
        process={
            "B2_APPLICATION_KEY_ID": "process-id",
            "B2_APPLICATION_KEY": "process-key",
        },
        reader=lambda ref: reads.append(ref) or material,
    )

    assert reads == []
    assert loaded.backup is not None
    assert loaded.backup.application_key_id == "process-id"
    assert loaded.backup.application_key == "process-key"
    assert loaded.capability_for(Capability.BACKUP).process_override is False


def test_partial_process_secret_pair_reads_bundle_once_for_missing_field() -> None:
    preferences, material = _backup_preferences()
    reads: list[SecretRef] = []

    loaded = load_test_configuration(
        ConfigurationUse.RUNTIME,
        preferences=preferences,
        process={"B2_APPLICATION_KEY_ID": "process-id"},
        reader=lambda ref: reads.append(ref) or material,
    )

    assert reads == [material.ref]
    assert loaded.backup is not None
    assert loaded.backup.application_key_id == "process-id"
    assert loaded.backup.application_key == "app-backup-secret"


def test_invalid_process_secret_short_circuits_whole_b2_keychain_bundle() -> None:
    preferences, material = _backup_preferences()
    reads: list[SecretRef] = []

    loaded = load_test_configuration(
        ConfigurationUse.RUNTIME,
        preferences=preferences,
        process={"B2_APPLICATION_KEY_ID": ""},
        reader=lambda ref: reads.append(ref) or material,
    )

    assert reads == []
    assert loaded.backup is None
    issue = issue_for(loaded, Capability.BACKUP)
    assert issue.code is ConfigurationIssueCode.EFFECTIVE_CONFIGURATION_INVALID
    assert "process environment" in issue.action.lower()


def _backup_preferences():
    base, material = provider_preferences(SecretId.BACKUP, enabled=True)
    preferences = AppPreferences(
        values=(
            PreferenceValue(PreferenceKey.B2_ENDPOINT, "https://s3.example.invalid"),
            PreferenceValue(PreferenceKey.B2_REGION, "region"),
            PreferenceValue(PreferenceKey.B2_BUCKET_NAME, "bucket"),
        ),
        capabilities=base.capabilities,
        secret_refs=base.secret_refs,
    )
    return preferences, material

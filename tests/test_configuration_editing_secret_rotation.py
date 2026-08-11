"""Immutable secret-generation ordering for native configuration edits."""

from __future__ import annotations

import pytest
from configuration_editing_fakes import (
    FakePreferences,
    FakeSecrets,
    backup_bundle,
    service,
    transcription_bundle,
)

from meeting_memory.service.preference_store import snapshot_for_preferences
from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration import (
    AppPreferences,
    CapabilityPreference,
    SecretId,
    SecretMaterial,
    SecretRef,
)
from meeting_memory.types.configuration_editing import (
    ConfigurationChange,
    ConfigurationField,
    ConfigurationSaveState,
    ConfigurationValue,
)


def test_stale_bound_snapshot_rejects_before_keychain_write() -> None:
    store = FakePreferences(AppPreferences())
    secrets = FakeSecrets()
    editor = service(store=store, secrets=secrets)
    view = editor.open(Capability.TRANSCRIPTION)
    store.snapshot = snapshot_for_preferences(
        AppPreferences(capabilities=(CapabilityPreference(Capability.TRANSCRIPTION, False),))
    )

    outcome = editor.save(
        ConfigurationChange(
            view.edit_id,
            Capability.TRANSCRIPTION,
            True,
            view.fields,
            transcription_bundle("secret-sentinel"),
            disclosure_confirmed=True,
        )
    )

    assert outcome.state is ConfigurationSaveState.PREFERENCES_CONFLICT
    assert secrets.writes == secrets.deletes == []
    assert store.cas_calls == 0


def test_store_returning_existing_active_ref_never_deletes_or_activates_it() -> None:
    old_ref = SecretRef(SecretId.TRANSCRIPTION, "a" * 32)
    preferences = AppPreferences(secret_refs=(old_ref,))
    store = FakePreferences(preferences)
    secrets = FakeSecrets(
        materials={old_ref: SecretMaterial(old_ref, transcription_bundle("old-secret"))},
        returned_ref=old_ref,
    )
    editor = service(store=store, secrets=secrets)
    view = editor.open(Capability.TRANSCRIPTION)

    outcome = editor.save(
        ConfigurationChange(
            view.edit_id,
            Capability.TRANSCRIPTION,
            True,
            view.fields,
            transcription_bundle("new-secret"),
            disclosure_confirmed=True,
        )
    )

    assert outcome.state is ConfigurationSaveState.CLEANUP_FAILED
    assert secrets.deletes == []
    assert store.cas_calls == 0
    assert store.snapshot.preferences.secret_ref_for(SecretId.TRANSCRIPTION) == old_ref


def test_wrong_provider_ref_is_untrusted_and_never_deleted() -> None:
    wrong_ref = SecretRef(SecretId.NOTES, "b" * 32)
    store = FakePreferences(AppPreferences())
    secrets = FakeSecrets(returned_ref=wrong_ref)
    editor = service(store=store, secrets=secrets)
    view = editor.open(Capability.TRANSCRIPTION)

    outcome = editor.save(
        ConfigurationChange(
            view.edit_id,
            Capability.TRANSCRIPTION,
            True,
            view.fields,
            transcription_bundle("new-secret"),
            disclosure_confirmed=True,
        )
    )

    assert outcome.state is ConfigurationSaveState.CLEANUP_FAILED
    assert secrets.deletes == []
    assert store.cas_calls == 0


def test_durable_rotation_activates_new_ref_then_deletes_only_old_ref() -> None:
    old_ref = SecretRef(SecretId.BACKUP, "c" * 32)
    preferences = AppPreferences(secret_refs=(old_ref,))
    operations: list[str] = []
    store = FakePreferences(preferences, operations=operations)
    secrets = FakeSecrets(
        materials={old_ref: SecretMaterial(old_ref, backup_bundle("old-id", "old-key"))},
        operations=operations,
    )
    editor = service(store=store, secrets=secrets)
    view = editor.open(Capability.BACKUP)

    outcome = editor.save(
        ConfigurationChange(
            view.edit_id,
            Capability.BACKUP,
            True,
            _valid_backup_fields(view.fields),
            backup_bundle("new-id", "new-key"),
            disclosure_confirmed=True,
        )
    )

    new_ref = secrets.writes[0]
    assert outcome.state is ConfigurationSaveState.SAVED
    assert store.snapshot.preferences.secret_ref_for(SecretId.BACKUP) == new_ref
    assert secrets.deletes == [old_ref]
    assert operations == ["secret_write", "preferences_cas", "secret_delete"]


def test_old_ref_cleanup_failure_does_not_undo_saved_rotation() -> None:
    old_ref = SecretRef(SecretId.TRANSCRIPTION, "d" * 32)
    preferences = AppPreferences(secret_refs=(old_ref,))
    store = FakePreferences(preferences)
    secrets = FakeSecrets(
        materials={old_ref: SecretMaterial(old_ref, transcription_bundle("old-secret"))},
        delete_fails_for=old_ref,
    )
    editor = service(store=store, secrets=secrets)
    view = editor.open(Capability.TRANSCRIPTION)

    outcome = editor.save(
        ConfigurationChange(
            view.edit_id,
            Capability.TRANSCRIPTION,
            True,
            view.fields,
            transcription_bundle("new-secret"),
            disclosure_confirmed=True,
        )
    )

    assert outcome.state is ConfigurationSaveState.SAVED_CLEANUP_FAILED
    assert outcome.pause_current_session is True
    assert outcome.restart_required is True
    assert store.snapshot.preferences.secret_ref_for(SecretId.TRANSCRIPTION) == secrets.writes[0]


def test_partial_process_setting_is_reported_without_exposing_value() -> None:
    editor = service(
        process={"B2_REGION": "process-region-sentinel"},
    )

    view = editor.open(Capability.BACKUP)

    assert view.process_present is True
    assert view.process_reenables is False
    assert "process-region-sentinel" not in repr(view)


def test_invalid_required_process_value_cannot_claim_reenable() -> None:
    view = service(process={"B2_ENDPOINT": ""}).open(Capability.BACKUP)

    assert view.process_present is True
    assert view.process_reenables is False


@pytest.mark.parametrize(
    ("behavior", "state"),
    [
        ("install_then_raise", ConfigurationSaveState.DURABILITY_UNCERTAIN),
        ("unknown", ConfigurationSaveState.ACTIVATION_UNCERTAIN),
    ],
)
def test_uncertain_rotation_retains_old_and_new_refs(
    behavior: str,
    state: ConfigurationSaveState,
) -> None:
    old_ref = SecretRef(SecretId.TRANSCRIPTION, "e" * 32)
    preferences = AppPreferences(secret_refs=(old_ref,))
    store = FakePreferences(preferences, behavior=behavior)
    secrets = FakeSecrets(
        materials={old_ref: SecretMaterial(old_ref, transcription_bundle("old-secret"))}
    )
    editor = service(store=store, secrets=secrets)
    view = editor.open(Capability.TRANSCRIPTION)

    outcome = editor.save(
        ConfigurationChange(
            view.edit_id,
            Capability.TRANSCRIPTION,
            True,
            view.fields,
            transcription_bundle("new-secret"),
            disclosure_confirmed=True,
        )
    )

    assert outcome.state is state
    assert secrets.deletes == []
    assert secrets.writes[0] != old_ref


def _valid_backup_fields(fields) -> tuple[ConfigurationField, ...]:
    values = {
        "B2_ENDPOINT": "https://s3.example.com",
        "B2_REGION": "us-west-004",
        "B2_BUCKET_NAME": "bucket",
    }
    return tuple(
        ConfigurationField(field.key, ConfigurationValue(values[field.key.value]))
        for field in fields
    )

"""Capability-scoped configuration editing and activation tests."""

from __future__ import annotations

from configuration_editing_fakes import (
    FakePreferences,
    FakeSecrets,
    IdFactory,
    backup_bundle,
    complete_legacy_backup,
    notes_bundle,
    service,
    transcription_bundle,
    value,
)

from meeting_memory.service.configuration_editing import CapabilityConfigurationService
from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration import (
    AppPreferences,
    CapabilityPreference,
    PreferenceKey,
    PreferenceValue,
    SecretId,
    SecretMaterial,
    SecretRef,
    SettingKey,
)
from meeting_memory.types.configuration_editing import (
    ConfigurationChange,
    ConfigurationField,
    ConfigurationSaveState,
    ConfigurationValue,
    SecretAvailability,
)


def test_open_uses_only_app_values_and_reads_exact_capability_ref() -> None:
    ref = SecretRef(SecretId.BACKUP, "a" * 32)
    preferences = AppPreferences(
        values=(PreferenceValue(PreferenceKey.B2_BUCKET_NAME, "app-bucket"),),
        capabilities=(CapabilityPreference(Capability.BACKUP, True),),
        secret_refs=(ref,),
    )
    secrets = FakeSecrets({ref: SecretMaterial(ref, backup_bundle("stored-id", "stored-secret"))})
    editor = service(
        preferences,
        secrets=secrets,
        process={
            "B2_APPLICATION_KEY_ID": "process-id",
            "B2_APPLICATION_KEY": "process-secret",
            "B2_ENDPOINT": "https://s3.process.example.com",
            "B2_REGION": "process-region",
            "B2_BUCKET_NAME": "process-sentinel",
        },
    )

    view = editor.open(Capability.BACKUP)

    assert secrets.reads == [ref]
    assert view.secret_availability is SecretAvailability.AVAILABLE
    assert view.process_present is True
    assert view.process_reenables is True
    assert value(view.fields, SettingKey.B2_BUCKET_NAME) == "app-bucket"
    assert "process-sentinel" not in repr(view)


def test_open_core_and_calendar_never_read_generic_keychain() -> None:
    secrets = FakeSecrets()
    editor = service(AppPreferences(), secrets=secrets)
    recording_view = editor.open(Capability.RECORDING_CORE)
    calendar_view = editor.open(Capability.CALENDAR)

    assert recording_view.secret_availability is SecretAvailability.NONE
    assert calendar_view.secret_availability is SecretAvailability.NONE
    assert secrets.reads == []


def test_calendar_enable_saves_nonsecret_configuration_without_generic_secret(
    tmp_path,
) -> None:
    store = FakePreferences(AppPreferences())
    secrets = FakeSecrets()
    editor = service(store=store, secrets=secrets)
    view = editor.open(Capability.CALENDAR)
    fields = tuple(
        ConfigurationField(field.key, ConfigurationValue(str(tmp_path / "oauth.json")))
        if field.key is SettingKey.GOOGLE_CALENDAR_CREDENTIALS_FILE
        else field
        for field in view.fields
    )

    outcome = editor.save(
        ConfigurationChange(
            view.edit_id,
            Capability.CALENDAR,
            True,
            fields,
            disclosure_confirmed=True,
        )
    )

    assert outcome.state is ConfigurationSaveState.SAVED
    assert store.snapshot.preferences.enabled_for(Capability.CALENDAR) is True
    assert secrets.reads == secrets.writes == secrets.deletes == []


def test_blank_secret_preserves_only_verified_available_reference() -> None:
    ref = SecretRef(SecretId.NOTES, "b" * 32)
    preferences = AppPreferences(
        capabilities=(CapabilityPreference(Capability.NOTES, True),),
        secret_refs=(ref,),
    )
    material = SecretMaterial(ref, notes_bundle("stored-secret"))
    store = FakePreferences(preferences)
    secrets = FakeSecrets({ref: material})
    editor = service(store=store, secrets=secrets)
    view = editor.open(Capability.NOTES)

    outcome = editor.save(
        ConfigurationChange(
            view.edit_id,
            Capability.NOTES,
            True,
            view.fields,
            disclosure_confirmed=True,
        )
    )

    assert outcome.state is ConfigurationSaveState.SAVED
    assert store.snapshot.preferences.secret_ref_for(SecretId.NOTES) == ref
    assert secrets.writes == []
    assert secrets.deletes == []


def test_blank_secret_with_missing_or_unreadable_ref_is_rejected() -> None:
    ref = SecretRef(SecretId.TRANSCRIPTION, "c" * 32)
    preferences = AppPreferences(secret_refs=(ref,))
    store = FakePreferences(preferences)
    editor = service(store=store, secrets=FakeSecrets())
    view = editor.open(Capability.TRANSCRIPTION)

    outcome = editor.save(
        ConfigurationChange(
            view.edit_id,
            Capability.TRANSCRIPTION,
            True,
            view.fields,
            disclosure_confirmed=True,
        )
    )

    assert view.secret_availability is SecretAvailability.UNAVAILABLE
    assert outcome.state is ConfigurationSaveState.REJECTED
    assert store.cas_calls == 0


def test_disable_ignores_blank_fields_and_preserves_values_and_ref(tmp_path) -> None:
    ref = SecretRef(SecretId.BACKUP, "d" * 32)
    preferences = AppPreferences(
        values=(PreferenceValue(PreferenceKey.B2_BUCKET_NAME, "managed-bucket"),),
        secret_refs=(ref,),
    )
    store = FakePreferences(preferences)
    secrets = FakeSecrets()
    env = tmp_path / ".env"
    env.write_text(complete_legacy_backup(), encoding="utf-8")
    editor = CapabilityConfigurationService(
        preference_store=store,
        secret_store=secrets,
        env_path=env,
        process_environment={},
        id_factory=IdFactory(),
    )
    view = editor.open(Capability.BACKUP)
    blank_fields = tuple(
        ConfigurationField(field.key, ConfigurationValue("")) for field in view.fields
    )

    outcome = editor.save(ConfigurationChange(view.edit_id, Capability.BACKUP, False, blank_fields))

    saved = store.snapshot.preferences
    assert outcome.state is ConfigurationSaveState.SAVED
    assert outcome.pause_current_session is True
    assert outcome.restart_required is False
    assert saved.enabled_for(Capability.BACKUP) is False
    assert saved.values == preferences.values
    assert saved.secret_refs == preferences.secret_refs
    assert secrets.writes == secrets.deletes == []


def test_keep_compatibility_changes_only_tri_state() -> None:
    preferences = AppPreferences(
        values=(PreferenceValue(PreferenceKey.ANTHROPIC_MODEL, "managed-model"),),
        capabilities=(CapabilityPreference(Capability.NOTES, False),),
    )
    store = FakePreferences(preferences)
    editor = service(store=store)
    view = editor.open(Capability.NOTES)
    blank = tuple(ConfigurationField(item.key, ConfigurationValue("")) for item in view.fields)

    outcome = editor.save(
        ConfigurationChange(
            view.edit_id,
            Capability.NOTES,
            None,
            blank,
            disclosure_confirmed=True,
        )
    )

    saved = store.snapshot.preferences
    assert outcome.state is ConfigurationSaveState.SAVED
    assert saved.enabled_for(Capability.NOTES) is None
    assert saved.values == preferences.values


def test_new_secret_is_deleted_after_proven_precommit_conflict() -> None:
    store = FakePreferences(AppPreferences(), behavior="conflict")
    secrets = FakeSecrets()
    editor = service(store=store, secrets=secrets)
    view = editor.open(Capability.TRANSCRIPTION)

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
    assert secrets.deletes == [secrets.writes[0]]
    assert store.snapshot.preferences == AppPreferences()


def test_visible_late_failure_retains_new_secret_and_reports_durability() -> None:
    store = FakePreferences(AppPreferences(), behavior="install_then_raise")
    secrets = FakeSecrets()
    editor = service(store=store, secrets=secrets)
    view = editor.open(Capability.TRANSCRIPTION)

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

    assert outcome.state is ConfigurationSaveState.DURABILITY_UNCERTAIN
    assert outcome.pause_current_session is True
    assert secrets.deletes == []


def test_unknown_cas_visibility_retains_new_secret() -> None:
    store = FakePreferences(AppPreferences(), behavior="unknown")
    secrets = FakeSecrets()
    editor = service(store=store, secrets=secrets)
    view = editor.open(Capability.TRANSCRIPTION)

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

    assert outcome.state is ConfigurationSaveState.ACTIVATION_UNCERTAIN
    assert outcome.pause_current_session is True
    assert secrets.deletes == []


def test_unchanged_consumes_edit_without_cas_or_pause() -> None:
    store = FakePreferences(AppPreferences())
    editor = service(store=store)
    view = editor.open(Capability.RECORDING_CORE)

    first = editor.save(
        ConfigurationChange(view.edit_id, Capability.RECORDING_CORE, None, view.fields)
    )
    second = editor.save(
        ConfigurationChange(view.edit_id, Capability.RECORDING_CORE, None, view.fields)
    )

    assert first.state is ConfigurationSaveState.SAVED
    assert second.state is ConfigurationSaveState.REJECTED
    assert store.cas_calls == 1

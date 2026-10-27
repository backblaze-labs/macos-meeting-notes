"""Provider selection and external-processing consent regression tests."""

from meeting_memory.config.resolution import resolve_configuration
from meeting_memory.service.configuration_loader import load_configuration
from meeting_memory.service.preference_store import snapshot_for_preferences
from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration import (
    AppPreferences,
    CapabilityPreference,
    PreferenceKey,
    PreferenceValue,
    SecretId,
    SecretRef,
    SettingKey,
)
from meeting_memory.types.configuration_resolution import ConfigurationUse


def resolve(*, process=None, legacy=None, preferences=None):
    return resolve_configuration(
        process_environment=process or {},
        legacy_environment=legacy or {},
        preferences=preferences or AppPreferences(),
        app_secrets=(),
    )


def test_new_and_inherited_key_profiles_default_local():
    for process, legacy in (
        ({}, {}),
        ({"ASSEMBLYAI_API_KEY": "old-key"}, {}),
        ({}, {"ASSEMBLYAI_API_KEY": "old-key"}),
    ):
        result = resolve(process=process, legacy=legacy)
        assert result.value_for(SettingKey.TRANSCRIPTION_PROVIDER) == "local"
        assert result.capability_for(Capability.TRANSCRIPTION).enabled
        assert not result.capability_for(Capability.TRANSCRIPTION).process_override


def test_explicit_disable_survives_inherited_process_key():
    preferences = AppPreferences(
        capabilities=(CapabilityPreference(Capability.TRANSCRIPTION, False),)
    )
    result = resolve(preferences=preferences, process={"ASSEMBLYAI_API_KEY": "old-key"})
    assert not result.capability_for(Capability.TRANSCRIPTION).enabled


def test_remote_process_requires_both_explicit_selection_and_versioned_consent():
    process = {"TRANSCRIPTION_PROVIDER": "assemblyai", "ASSEMBLYAI_API_KEY": "key"}
    assert not resolve(process=process).capability_for(Capability.TRANSCRIPTION).enabled
    process["ASSEMBLYAI_CONSENT"] = "external-audio-v1"
    assert resolve(process=process).capability_for(Capability.TRANSCRIPTION).enabled
    process["ASSEMBLYAI_CONSENT"] = "true"
    assert not resolve(process=process).capability_for(Capability.TRANSCRIPTION).enabled


def test_legacy_key_and_import_do_not_authorize_cloud():
    result = resolve(
        legacy={
            "ASSEMBLYAI_API_KEY": "key",
            "TRANSCRIPTION_PROVIDER": "assemblyai",
            "ASSEMBLYAI_CONSENT": "external-audio-v1",
        }
    )
    assert result.value_for(SettingKey.TRANSCRIPTION_PROVIDER) == "local"


def test_local_never_reads_old_cloud_keychain_reference(tmp_path):
    preferences = AppPreferences(
        capabilities=(CapabilityPreference(Capability.TRANSCRIPTION, True),),
        secret_refs=(SecretRef(SecretId.TRANSCRIPTION, "a" * 32),),
    )
    reads = []
    loaded = load_configuration(
        ConfigurationUse.RUNTIME,
        env_file=None,
        process_environment={},
        preference_reader=lambda: snapshot_for_preferences(preferences),
        secret_reader=lambda ref: reads.append(ref),
    )
    assert reads == []
    assert loaded.transcription.provider.value == "local"
    assert loaded.transcription.api_key is None


def test_local_selection_keeps_unrelated_preferences_and_cloud_secret_ref():
    preferences = AppPreferences(
        values=(PreferenceValue(PreferenceKey.MEETINGS_DIR, "/tmp/meetings"),),
        secret_refs=(SecretRef(SecretId.TRANSCRIPTION, "a" * 32),),
    )
    result = resolve(preferences=preferences)
    assert result.value_for(SettingKey.MEETINGS_DIR) == "/tmp/meetings"
    assert preferences.secret_ref_for(SecretId.TRANSCRIPTION) is not None


def test_local_edit_reuses_cloud_reference_without_reading_or_rewriting_it():
    from configuration_editing_fakes import FakePreferences, FakeSecrets, service

    from meeting_memory.types.configuration_editing import ConfigurationChange

    ref = SecretRef(SecretId.TRANSCRIPTION, "a" * 32)
    preferences = AppPreferences(
        values=(PreferenceValue(PreferenceKey.MAX_RECORDING_MINUTES, "90"),),
        secret_refs=(ref,),
    )
    store, secrets = FakePreferences(preferences), FakeSecrets()
    editor = service(store=store, secrets=secrets)
    view = editor.open(Capability.TRANSCRIPTION)
    outcome = editor.save(
        ConfigurationChange(
            view.edit_id,
            view.capability,
            True,
            view.fields,
            disclosure_confirmed=True,
        )
    )
    assert outcome.restart_required
    assert secrets.reads == secrets.writes == secrets.deletes == []
    assert store.snapshot.preferences.secret_ref_for(SecretId.TRANSCRIPTION) == ref
    assert store.snapshot.preferences.value_for(PreferenceKey.MAX_RECORDING_MINUTES) == "90"


def test_external_save_requires_versioned_acceptance_even_with_generic_disclosure():
    from configuration_editing_fakes import service

    from meeting_memory.types.configuration_editing import (
        ConfigurationChange,
        ConfigurationField,
        ConfigurationSaveState,
        ConfigurationValue,
    )

    editor = service()
    view = editor.open(Capability.TRANSCRIPTION)
    fields = tuple(
        ConfigurationField(field.key, ConfigurationValue("assemblyai"))
        if field.key is SettingKey.TRANSCRIPTION_PROVIDER
        else field
        for field in view.fields
    )
    outcome = editor.save(
        ConfigurationChange(
            view.edit_id,
            view.capability,
            True,
            fields,
            disclosure_confirmed=True,
        )
    )
    assert outcome.state is ConfigurationSaveState.REJECTED


def test_mixed_valid_process_selection_preserves_active_cloud_keychain_reference():
    from configuration_loader_fakes import provider_preferences

    preferences, material = provider_preferences(SecretId.TRANSCRIPTION, enabled=True)
    for process in (
        {"TRANSCRIPTION_PROVIDER": "assemblyai"},
        {"ASSEMBLYAI_CONSENT": "external-audio-v1"},
        {"TRANSCRIPTION_PROVIDER": "assemblyai", "ASSEMBLYAI_CONSENT": "external-audio-v1"},
    ):
        reads = []
        loaded = load_configuration(
            ConfigurationUse.RUNTIME,
            env_file=None,
            process_environment=process,
            preference_reader=lambda: snapshot_for_preferences(preferences),
            secret_reader=lambda ref: reads.append(ref) or material,
        )
        assert reads == [material.ref]
        assert loaded.transcription.api_key == material.bundle.values[0].value


def test_invalid_cloud_process_fields_mask_app_values_without_keychain_reads():
    from configuration_loader_fakes import provider_preferences

    preferences, material = provider_preferences(SecretId.TRANSCRIPTION, enabled=True)
    for process in (
        {"ASSEMBLYAI_API_KEY": ""},
        {"TRANSCRIPTION_PROVIDER": "invalid"},
        {"ASSEMBLYAI_CONSENT": "true"},
    ):
        reads = []
        loaded = load_configuration(
            ConfigurationUse.RUNTIME,
            env_file=None,
            process_environment=process,
            preference_reader=lambda: snapshot_for_preferences(preferences),
            secret_reader=lambda ref: reads.append(ref) or material,
        )
        assert reads == []
        assert loaded.transcription is None

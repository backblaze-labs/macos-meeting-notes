"""Consent guards for returning app-disabled capabilities to legacy compatibility."""

from __future__ import annotations

import pytest
from configuration_editing_fakes import FakePreferences, FakeSecrets, IdFactory

from meeting_memory.service.configuration_editing import (
    CapabilityConfigurationService,
    ConfigurationEditingError,
)
from meeting_memory.service.configuration_loader import load_configuration
from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration import AppPreferences, CapabilityPreference
from meeting_memory.types.configuration_editing import (
    ConfigurationChange,
    ConfigurationSaveOutcome,
    ConfigurationSaveState,
)
from meeting_memory.types.configuration_resolution import ConfigurationUse

OPTIONALS = (
    Capability.TRANSCRIPTION,
    Capability.BACKUP,
    Capability.CALENDAR,
    Capability.NOTES,
)
PROCESS_GROUPS = {
    Capability.TRANSCRIPTION: {"ASSEMBLYAI_API_KEY": "process-transcription"},
    Capability.BACKUP: {
        "B2_APPLICATION_KEY_ID": "process-id",
        "B2_APPLICATION_KEY": "process-backup",
        "B2_ENDPOINT": "https://s3.example.com",
        "B2_REGION": "us-west-004",
        "B2_BUCKET_NAME": "process-bucket",
    },
    Capability.CALENDAR: {"GOOGLE_CALENDAR_CREDENTIALS_FILE": "/tmp/oauth.json"},
    Capability.NOTES: {"ANTHROPIC_API_KEY": "process-notes"},
}


def test_legacy_compatibility_requires_disclosure_and_reenables_on_restart(
    tmp_path,
) -> None:
    env = tmp_path / ".env"
    original = _complete_legacy_environment(tmp_path).encode()
    env.write_bytes(original)

    for capability in OPTIONALS:
        preferences = AppPreferences(capabilities=(CapabilityPreference(capability, False),))
        store = FakePreferences(preferences)
        secrets = FakeSecrets()
        editor = _service(store, secrets, env)
        view = editor.open(capability)

        rejected = editor.save(ConfigurationChange(view.edit_id, capability, None, view.fields))

        assert view.legacy_reenables is True
        assert rejected.state is ConfigurationSaveState.REJECTED
        assert rejected.legacy_reenables is True
        assert store.cas_calls == 0

        confirmed_view = editor.open(capability)
        saved = editor.save(
            ConfigurationChange(
                confirmed_view.edit_id,
                capability,
                None,
                confirmed_view.fields,
                disclosure_confirmed=True,
            )
        )
        loaded = load_configuration(
            ConfigurationUse.RUNTIME,
            env_file=env,
            process_environment={},
            preference_reader=store.load_snapshot,
            secret_reader=secrets.read,
        )

        assert saved.state is ConfigurationSaveState.SAVED
        assert loaded.capability_enabled(capability) is True
        assert env.read_bytes() == original


def test_false_to_compatibility_consent_is_safe_against_env_toctou(tmp_path) -> None:
    env = tmp_path / ".env"
    store = FakePreferences(
        AppPreferences(capabilities=(CapabilityPreference(Capability.TRANSCRIPTION, False),))
    )
    editor = _service(store, FakeSecrets(), env)
    view = editor.open(Capability.TRANSCRIPTION)
    env.write_text("ASSEMBLYAI_API_KEY=late-legacy-secret\n", encoding="utf-8")

    outcome = editor.save(
        ConfigurationChange(
            view.edit_id,
            Capability.TRANSCRIPTION,
            None,
            view.fields,
        )
    )

    assert view.legacy_reenables is False
    assert outcome.state is ConfigurationSaveState.REJECTED
    assert store.cas_calls == 0
    assert store.snapshot.preferences.enabled_for(Capability.TRANSCRIPTION) is False
    assert "late-legacy-secret" not in repr(outcome)


def test_invalid_legacy_destination_does_not_claim_reenable(tmp_path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        _complete_legacy_environment(tmp_path).replace(
            "B2_ENDPOINT=https://s3.example.com",
            "B2_ENDPOINT=http://unsafe.example.com",
        ),
        encoding="utf-8",
    )
    preferences = AppPreferences(capabilities=(CapabilityPreference(Capability.BACKUP, False),))

    view = _service(FakePreferences(preferences), FakeSecrets(), env).open(Capability.BACKUP)

    assert view.legacy_reenables is False


@pytest.mark.parametrize("capability", OPTIONALS)
def test_repeated_disable_pauses_complete_process_override(capability) -> None:
    store = FakePreferences(AppPreferences(capabilities=(CapabilityPreference(capability, False),)))
    secrets = FakeSecrets()
    editor = CapabilityConfigurationService(
        preference_store=store,
        secret_store=secrets,
        env_path=None,
        process_environment=PROCESS_GROUPS[capability],
        id_factory=IdFactory(),
    )
    view = editor.open(capability)

    outcome = editor.save(ConfigurationChange(view.edit_id, capability, False, view.fields))

    assert outcome.state is ConfigurationSaveState.SESSION_PAUSED
    assert outcome.pause_current_session is True
    assert outcome.restart_required is False
    assert outcome.process_reenables is True
    assert store.cas_calls == 0
    assert secrets.writes == secrets.deletes == []


@pytest.mark.parametrize(
    "process",
    (
        {"B2_REGION": "us-west-004"},
        {
            **PROCESS_GROUPS[Capability.BACKUP],
            "B2_ENDPOINT": "http://unsafe.example.com",
        },
    ),
)
def test_partial_or_invalid_process_disable_remains_unchanged(process) -> None:
    store = FakePreferences(
        AppPreferences(capabilities=(CapabilityPreference(Capability.BACKUP, False),))
    )
    editor = CapabilityConfigurationService(
        preference_store=store,
        secret_store=FakeSecrets(),
        env_path=None,
        process_environment=process,
        id_factory=IdFactory(),
    )
    view = editor.open(Capability.BACKUP)

    outcome = editor.save(ConfigurationChange(view.edit_id, Capability.BACKUP, False, view.fields))

    assert outcome.state is ConfigurationSaveState.UNCHANGED
    assert outcome.pause_current_session is False
    assert outcome.process_reenables is False
    assert store.cas_calls == 0


def test_legacy_masked_disable_remains_unchanged(tmp_path) -> None:
    env = tmp_path / ".env"
    env.write_text(_complete_legacy_environment(tmp_path), encoding="utf-8")
    store = FakePreferences(
        AppPreferences(capabilities=(CapabilityPreference(Capability.BACKUP, False),))
    )
    editor = _service(store, FakeSecrets(), env)
    view = editor.open(Capability.BACKUP)

    outcome = editor.save(ConfigurationChange(view.edit_id, Capability.BACKUP, False, view.fields))

    assert outcome.state is ConfigurationSaveState.UNCHANGED
    assert outcome.pause_current_session is False
    assert store.cas_calls == 0


@pytest.mark.parametrize(
    ("capability", "process_reenables"),
    ((Capability.RECORDING_CORE, True), (Capability.BACKUP, False)),
)
def test_session_paused_rejects_inconsistent_source(capability, process_reenables) -> None:
    with pytest.raises(ValueError, match="inconsistent"):
        ConfigurationSaveOutcome(
            ConfigurationSaveState.SESSION_PAUSED,
            capability,
            "Safe summary.",
            "Safe action.",
            pause_current_session=True,
            process_reenables=process_reenables,
        )


def test_untyped_save_is_rejected_with_sanitized_error() -> None:
    with pytest.raises(ConfigurationEditingError, match="change was rejected") as caught:
        _service(FakePreferences(AppPreferences()), FakeSecrets(), None).save(
            object()  # type: ignore[arg-type]
        )

    assert "object" not in str(caught.value)


def _service(store, secrets, env) -> CapabilityConfigurationService:
    return CapabilityConfigurationService(
        preference_store=store,
        secret_store=secrets,
        env_path=env,
        process_environment={},
        id_factory=IdFactory(),
    )


def _complete_legacy_environment(tmp_path) -> str:
    return "\n".join(
        (
            "ASSEMBLYAI_API_KEY=legacy-transcription-secret",
            "B2_APPLICATION_KEY_ID=legacy-id",
            "B2_APPLICATION_KEY=legacy-backup-secret",
            "B2_ENDPOINT=https://s3.example.com",
            "B2_REGION=us-west-004",
            "B2_BUCKET_NAME=legacy-bucket",
            f"GOOGLE_CALENDAR_CREDENTIALS_FILE={tmp_path / 'credentials.json'}",
            "ANTHROPIC_API_KEY=legacy-notes-secret",
            "",
        )
    )

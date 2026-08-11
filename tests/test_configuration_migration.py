"""Explicit Stage 4C preview and confirmed-apply tests."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from configuration_migration_fakes import FakePreferenceStore, FakeSecretStore

from meeting_memory.service.configuration_migration import EnvironmentMigrationService
from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration import (
    AppPreferences,
    CapabilityPreference,
    PreferenceKey,
    SettingKey,
)
from meeting_memory.types.configuration_migration import (
    MigrationConfirmation,
    MigrationFieldState,
    MigrationOutcomeState,
    MigrationPreviewId,
    MigrationPreviewState,
)


def test_missing_unknown_invalid_and_corrupt_sources_never_create_a_binding(
    tmp_path: Path,
) -> None:
    preferences = FakePreferenceStore()
    secrets = FakeSecretStore()
    service = _service(tmp_path / ".env", preferences, secrets)

    missing = service.preview(process_environment={"ASSEMBLYAI_API_KEY": "process-secret"})
    (tmp_path / ".env").write_text("unknown=value\n", encoding="utf-8")
    unknown = service.preview()
    (tmp_path / ".env").write_text("ASSEMBLYAI_API_KEY=\n", encoding="utf-8")
    invalid = service.preview()
    preferences.load_error = RuntimeError("private parser sentinel")
    (tmp_path / ".env").write_text("ASSEMBLYAI_API_KEY=legacy-secret\n", encoding="utf-8")
    corrupt = service.preview(process_environment={"ASSEMBLYAI_API_KEY": "process-secret"})
    preferences.load_error = None
    duplicate_bytes = b"ASSEMBLYAI_API_KEY=secret-one\nASSEMBLYAI_API_KEY=secret-two\n"
    (tmp_path / ".env").write_bytes(duplicate_bytes)
    duplicate = service.preview()

    assert missing.state is MigrationPreviewState.EMPTY
    process_field = _field(missing, Capability.TRANSCRIPTION, SettingKey.ASSEMBLYAI_API_KEY)
    assert process_field.process_present is True
    assert unknown.state is MigrationPreviewState.EMPTY
    assert invalid.state is MigrationPreviewState.EMPTY
    assert (
        _field(invalid, Capability.TRANSCRIPTION, SettingKey.ASSEMBLYAI_API_KEY).state
        is MigrationFieldState.INVALID
    )
    assert corrupt.state is MigrationPreviewState.FAILED
    assert duplicate.state is MigrationPreviewState.FAILED
    assert (tmp_path / ".env").read_bytes() == duplicate_bytes
    for preview in (missing, unknown, invalid, corrupt, duplicate):
        outcome = service.apply(
            MigrationConfirmation(preview.preview_id, (Capability.TRANSCRIPTION,), True)
        )
        assert outcome.state is MigrationOutcomeState.REJECTED
    assert secrets.written == []
    assert preferences.cas_calls == []


def test_falsey_injected_stores_are_used_without_falling_back_to_real_stores(
    tmp_path: Path,
) -> None:
    class FalseyPreferences(FakePreferenceStore):
        def __bool__(self) -> bool:
            return False

    class FalseySecrets(FakeSecretStore):
        def __bool__(self) -> bool:
            return False

    env_path = tmp_path / ".env"
    env_path.write_text("ASSEMBLYAI_API_KEY=legacy-secret\n", encoding="utf-8")
    preferences = FalseyPreferences()
    secrets = FalseySecrets()
    service = _service(env_path, preferences, secrets)

    preview = service.preview()
    outcome = service.apply(
        MigrationConfirmation(preview.preview_id, (Capability.TRANSCRIPTION,), True)
    )

    assert outcome.state is MigrationOutcomeState.APPLIED
    assert len(preferences.cas_calls) == 1
    assert len(secrets.written) == 1


def test_confirmed_selection_writes_only_selected_secrets_then_one_atomic_cas(
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env"
    original = _complete_env(tmp_path)
    env_path.write_bytes(original)
    env_path.chmod(0o640)
    before = env_path.stat()
    preferences = FakePreferenceStore()
    secrets = FakeSecretStore()
    service = _service(env_path, preferences, secrets)

    preview = service.preview(process_environment={"B2_REGION": "process-region"})
    outcome = service.apply(
        MigrationConfirmation(
            preview.preview_id,
            (
                Capability.NOTES,
                Capability.RECORDING_CORE,
                Capability.BACKUP,
                Capability.CALENDAR,
            ),
            True,
        )
    )

    assert preview.state is MigrationPreviewState.READY
    assert outcome.state is MigrationOutcomeState.APPLIED
    assert outcome.selected == (
        Capability.RECORDING_CORE,
        Capability.BACKUP,
        Capability.CALENDAR,
        Capability.NOTES,
    )
    assert tuple(bundle.secret_id.value for bundle in secrets.written) == ("backup", "notes")
    assert len(preferences.cas_calls) == 1
    saved = preferences.snapshot.preferences
    assert saved.enabled_for(Capability.BACKUP) is True
    assert saved.enabled_for(Capability.CALENDAR) is True
    assert saved.enabled_for(Capability.NOTES) is True
    assert saved.enabled_for(Capability.TRANSCRIPTION) is None
    assert saved.value_for(PreferenceKey.MEETINGS_DIR) == "./private-meetings"
    assert saved.value_for(PreferenceKey.B2_REGION) == "legacy-region"
    assert all(item.capability is not Capability.RECORDING_CORE for item in saved.capabilities)
    after = env_path.stat()
    assert env_path.read_bytes() == original
    assert (after.st_ino, after.st_mode) == (before.st_ino, before.st_mode)


def test_process_values_are_presence_only_and_public_graphs_are_redacted(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("ASSEMBLYAI_API_KEY=legacy-secret-sentinel\n", encoding="utf-8")
    preferences = FakePreferenceStore()
    secrets = FakeSecretStore()
    service = _service(env_path, preferences, secrets)

    preview = service.preview(process_environment={"ASSEMBLYAI_API_KEY": "process-secret-sentinel"})
    outcome = service.apply(
        MigrationConfirmation(preview.preview_id, (Capability.TRANSCRIPTION,), True)
    )

    assert outcome.state is MigrationOutcomeState.APPLIED
    bundle = secrets.written[0]
    assert bundle.value_for(SettingKey.ASSEMBLYAI_API_KEY) == "legacy-secret-sentinel"
    public = f"{preview!r} {asdict(preview)!r} {outcome!r} {service!r}"
    for sentinel in (
        "legacy-secret-sentinel",
        "process-secret-sentinel",
        str(env_path),
        preferences.snapshot.revision or "revision-not-present",
    ):
        assert sentinel not in public


def test_explicit_disable_and_forged_or_replaced_confirmation_make_zero_writes(
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("ASSEMBLYAI_API_KEY=legacy-secret\n", encoding="utf-8")
    preferences = FakePreferenceStore(
        AppPreferences(
            capabilities=(CapabilityPreference(Capability.TRANSCRIPTION, False),),
        )
    )
    secrets = FakeSecretStore()
    service = _service(env_path, preferences, secrets)

    blocked = service.preview()
    rejected = service.apply(
        MigrationConfirmation(blocked.preview_id, (Capability.TRANSCRIPTION,), True)
    )
    preferences.snapshot = preferences.snapshot.__class__(AppPreferences(), None)
    first = service.preview()
    second = service.preview()
    forged = service.apply(
        MigrationConfirmation(MigrationPreviewId("f" * 32), (Capability.TRANSCRIPTION,), True)
    )
    replaced = service.apply(
        MigrationConfirmation(first.preview_id, (Capability.TRANSCRIPTION,), True)
    )
    applied = service.apply(
        MigrationConfirmation(second.preview_id, (Capability.TRANSCRIPTION,), True)
    )
    used = service.apply(
        MigrationConfirmation(second.preview_id, (Capability.TRANSCRIPTION,), True)
    )

    assert [item.state for item in (rejected, forged, replaced, applied, used)] == [
        MigrationOutcomeState.REJECTED,
        MigrationOutcomeState.REJECTED,
        MigrationOutcomeState.REJECTED,
        MigrationOutcomeState.APPLIED,
        MigrationOutcomeState.REJECTED,
    ]
    assert len(secrets.written) == 1
    assert len(preferences.cas_calls) == 1


def _service(path: Path, preferences, secrets) -> EnvironmentMigrationService:
    ids = iter(f"{number:032x}" for number in range(1, 20))
    return EnvironmentMigrationService(
        path,
        preference_store=preferences,
        secret_store=secrets,
        id_factory=lambda: next(ids),
    )


def _field(preview, capability: Capability, key: SettingKey):
    candidate = next(item for item in preview.candidates if item.capability is capability)
    return next(item for item in candidate.fields if item.key is key)


def _complete_env(tmp_path: Path) -> bytes:
    return (
        "MEETINGS_DIR=./private-meetings\n"
        "MAX_RECORDING_MINUTES=90\n"
        "ASSEMBLYAI_API_KEY=assembly-secret\n"
        "B2_APPLICATION_KEY_ID=b2-id\n"
        "B2_APPLICATION_KEY=b2-secret\n"
        "B2_ENDPOINT=https://s3.example.invalid\n"
        "B2_REGION=legacy-region\n"
        "B2_BUCKET_NAME=bucket\n"
        f"GOOGLE_CALENDAR_CREDENTIALS_FILE={tmp_path / 'credentials.json'}\n"
        "GOOGLE_CALENDAR_ID=primary\n"
        "KNOWN_SPEAKERS={}\n"
        "NOTIFY_MINUTES_BEFORE=5\n"
        "CALENDAR_POLL_INTERVAL=120\n"
        "ANTHROPIC_API_KEY=notes-secret\n"
        "ANTHROPIC_MODEL=model\n"
        f"SUMMARY_PROMPT_FILE={tmp_path / 'prompt.md'}\n"
    ).encode()

"""Stage 4B/4C composition integration with only temp stores and fake secrets."""

from __future__ import annotations

import threading
from pathlib import Path

from configuration_migration_fakes import FakeSecretStore

from meeting_memory.service.configuration_loader import load_configuration
from meeting_memory.service.configuration_migration import EnvironmentMigrationService
from meeting_memory.service.preference_store import PreferenceStore
from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration import SecretId, SettingKey
from meeting_memory.types.configuration_migration import (
    MigrationConfirmation,
    MigrationOutcomeState,
)
from meeting_memory.types.configuration_resolution import ConfigurationUse, SettingSource


def test_success_activates_composed_refs_process_still_wins_and_legacy_stays(
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env"
    original = (
        b"ASSEMBLYAI_API_KEY=legacy-assembly\n"
        b"B2_APPLICATION_KEY_ID=legacy-id\n"
        b"B2_APPLICATION_KEY=legacy-key\n"
        b"B2_ENDPOINT=https://s3.example.invalid\n"
        b"B2_REGION=legacy-region\n"
        b"B2_BUCKET_NAME=legacy-bucket\n"
        b"ANTHROPIC_API_KEY=legacy-notes\n"
    )
    env_path.write_bytes(original)
    preferences = PreferenceStore(tmp_path / "app" / "preferences.json")
    secrets = FakeSecretStore()
    service = EnvironmentMigrationService(
        env_path,
        preference_store=preferences,
        secret_store=secrets,
        id_factory=lambda: "a" * 32,
    )
    preview = service.preview(process_environment={"ASSEMBLYAI_API_KEY": "process-not-imported"})

    outcome = service.apply(
        MigrationConfirmation(
            preview.preview_id,
            (Capability.TRANSCRIPTION, Capability.BACKUP),
            True,
        )
    )

    assert outcome.state is MigrationOutcomeState.APPLIED
    assert env_path.read_bytes() == original
    reads: list[SecretId] = []
    loaded = load_configuration(
        ConfigurationUse.RUNTIME,
        env_file=env_path,
        process_environment={"ASSEMBLYAI_API_KEY": "effective-process"},
        preference_reader=preferences.load_snapshot,
        secret_reader=lambda ref: reads.append(ref.secret_id) or secrets.read(ref),
    )
    assert loaded.transcription is not None
    assert loaded.transcription.api_key == "effective-process"
    assert loaded.backup is not None
    assert loaded.backup.application_key == "legacy-key"
    assert loaded.notes is not None
    assert loaded.notes.api_key == "legacy-notes"
    assert reads == [SecretId.BACKUP]
    assert _source(loaded, SettingKey.ASSEMBLYAI_API_KEY) is SettingSource.PROCESS_ENV
    assert _source(loaded, SettingKey.B2_APPLICATION_KEY) is SettingSource.APP_KEYCHAIN
    assert _source(loaded, SettingKey.ANTHROPIC_API_KEY) is SettingSource.LEGACY_ENV


def test_unselected_capabilities_and_google_oauth_identity_are_never_touched(
    tmp_path: Path,
    monkeypatch,
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "GOOGLE_CALENDAR_CREDENTIALS_FILE=credentials.json\n"
        "GOOGLE_CALENDAR_ID=primary\n"
        "ASSEMBLYAI_API_KEY=assembly-secret\n",
        encoding="utf-8",
    )
    preferences = PreferenceStore(tmp_path / "app" / "preferences.json")
    secrets = FakeSecretStore()
    service = EnvironmentMigrationService(
        env_path,
        preference_store=preferences,
        secret_store=secrets,
        id_factory=lambda: "b" * 32,
    )
    preview = service.preview()

    outcome = service.apply(MigrationConfirmation(preview.preview_id, (Capability.CALENDAR,), True))

    assert outcome.state is MigrationOutcomeState.APPLIED
    assert secrets.written == []
    assert preferences.load().enabled_for(Capability.CALENDAR) is True
    assert preferences.load().enabled_for(Capability.TRANSCRIPTION) is None


def test_concurrent_first_activation_has_one_winner_and_one_typed_conflict(
    tmp_path: Path,
) -> None:
    for round_number in range(3):
        root = tmp_path / str(round_number)
        root.mkdir()
        env_path = root / ".env"
        original = b"ASSEMBLYAI_API_KEY=legacy-secret\n"
        env_path.write_bytes(original)
        preferences = PreferenceStore(root / "app" / "preferences.json")
        secrets = _LockedSecretStore()
        services = tuple(
            EnvironmentMigrationService(
                env_path,
                preference_store=preferences,
                secret_store=secrets,
                id_factory=lambda number=number: f"{number:032x}",
            )
            for number in (1, 2)
        )
        previews = tuple(service.preview() for service in services)
        barrier = threading.Barrier(3)
        outcomes = []

        def run(service, preview) -> None:
            barrier.wait(timeout=2)
            outcomes.append(
                service.apply(
                    MigrationConfirmation(
                        preview.preview_id,
                        (Capability.TRANSCRIPTION,),
                        True,
                    )
                )
            )

        threads = [
            threading.Thread(target=run, args=(service, preview))
            for service, preview in zip(services, previews, strict=True)
        ]
        for thread in threads:
            thread.start()
        barrier.wait(timeout=2)
        for thread in threads:
            thread.join(timeout=3)

        assert sorted(item.state for item in outcomes) == sorted(
            (MigrationOutcomeState.APPLIED, MigrationOutcomeState.PREFERENCES_CONFLICT)
        )
        saved_ref = preferences.load().secret_ref_for(SecretId.TRANSCRIPTION)
        assert saved_ref is not None
        assert set(secrets.materials) == {saved_ref}
        assert len(secrets.deleted) == 1
        assert env_path.read_bytes() == original


class _LockedSecretStore(FakeSecretStore):
    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()

    def write_new(self, bundle):
        with self._lock:
            return super().write_new(bundle)

    def delete(self, ref):
        with self._lock:
            return super().delete(ref)


def _source(loaded, key: SettingKey) -> SettingSource:
    return next(item.source for item in loaded.resolution.provenance if item.key is key)

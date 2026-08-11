"""Reference validation, single-use, and totality tests for Stage 4C."""

from __future__ import annotations

import threading
from pathlib import Path

from configuration_migration_fakes import FakePreferenceStore, FakeSecretStore

from meeting_memory.service import configuration_migration
from meeting_memory.service.configuration_migration import EnvironmentMigrationService
from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration import AppPreferences, SecretId, SecretRef
from meeting_memory.types.configuration_migration import (
    MigrationConfirmation,
    MigrationOutcomeState,
    MigrationPreviewState,
)


def test_invalid_returned_refs_never_delete_existing_or_foreign_references(
    tmp_path: Path,
) -> None:
    env_path = _provider_env(tmp_path)
    existing = SecretRef(SecretId.NOTES, "e" * 32)
    for returned in (existing, SecretRef(SecretId.BACKUP, "f" * 32)):
        preferences = FakePreferenceStore(AppPreferences(secret_refs=(existing,)))
        secrets = FakeSecretStore()
        secrets.return_ref = lambda _bundle, _created, returned=returned: returned
        service = _service(env_path, preferences, secrets)
        preview = service.preview()

        outcome = service.apply(_confirmation(preview, Capability.TRANSCRIPTION))

        assert outcome.state is MigrationOutcomeState.CLEANUP_FAILED
        assert existing not in secrets.deleted
        assert returned not in secrets.deleted
        assert preferences.cas_calls == []


def test_duplicate_returned_ref_cleans_once_and_same_confirmation_has_one_winner(
    tmp_path: Path,
) -> None:
    env_path = _provider_env(tmp_path)
    preferences = FakePreferenceStore()
    secrets = FakeSecretStore()
    first_ref: list[SecretRef] = []

    def duplicate(_bundle, created):
        if not first_ref:
            first_ref.append(created)
            return created
        return first_ref[0]

    secrets.return_ref = duplicate
    service = _service(env_path, preferences, secrets)
    preview = service.preview()
    outcome = service.apply(_confirmation(preview, Capability.TRANSCRIPTION, Capability.NOTES))

    assert outcome.state is MigrationOutcomeState.CLEANUP_FAILED
    assert secrets.deleted == [first_ref[0]]

    preferences = FakePreferenceStore()
    secrets = FakeSecretStore()
    service = _service(env_path, preferences, secrets)
    preview = service.preview()
    confirmation = _confirmation(preview, Capability.TRANSCRIPTION)
    outcomes = []
    threads = [
        threading.Thread(target=lambda: outcomes.append(service.apply(confirmation)))
        for _ in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert sorted(item.state for item in outcomes) == sorted(
        (MigrationOutcomeState.APPLIED, MigrationOutcomeState.REJECTED)
    )
    assert len(secrets.written) == 1
    assert len(preferences.cas_calls) == 1


def test_preview_and_apply_are_total_and_relative_path_is_anchored(
    tmp_path: Path,
    monkeypatch,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / ".env").write_text("ASSEMBLYAI_API_KEY=legacy-secret\n", encoding="utf-8")
    (second / ".env").write_text("ASSEMBLYAI_API_KEY=other-secret\n", encoding="utf-8")
    preferences = FakePreferenceStore()
    secrets = FakeSecretStore()
    monkeypatch.chdir(first)
    service = _service(Path(".env"), preferences, secrets)
    preview = service.preview()
    monkeypatch.chdir(second)

    outcome = service.apply(_confirmation(preview, Capability.TRANSCRIPTION))

    assert outcome.state is MigrationOutcomeState.APPLIED
    assert secrets.written[0].values[0].value == "legacy-secret"

    broken = EnvironmentMigrationService(
        first / ".env",
        preference_store=preferences,
        secret_store=secrets,
        id_factory=lambda: (_ for _ in ()).throw(RuntimeError("id sentinel")),
    )
    failed = broken.preview(process_environment=_HostileMapping())
    assert failed.state is MigrationPreviewState.FAILED
    assert "sentinel" not in repr(failed)

    service = _service(first / ".env", FakePreferenceStore(), FakeSecretStore())
    preview = service.preview()
    monkeypatch.setattr(
        configuration_migration,
        "build_migration_plan",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("plan sentinel")),
    )
    failed_apply = service.apply(_confirmation(preview, Capability.TRANSCRIPTION))
    assert failed_apply.state is MigrationOutcomeState.FAILED
    assert "sentinel" not in repr(failed_apply)


class _HostileMapping(dict):
    def keys(self):
        raise RuntimeError("mapping sentinel")


def _service(path: Path, preferences, secrets) -> EnvironmentMigrationService:
    ids = iter(f"{number:032x}" for number in range(1, 20))
    return EnvironmentMigrationService(
        path,
        preference_store=preferences,
        secret_store=secrets,
        id_factory=lambda: next(ids),
    )


def _confirmation(preview, *selected: Capability) -> MigrationConfirmation:
    return MigrationConfirmation(preview.preview_id, selected, True)


def _provider_env(tmp_path: Path) -> Path:
    path = tmp_path / ".env"
    path.write_text(
        "ASSEMBLYAI_API_KEY=assembly-secret\nANTHROPIC_API_KEY=notes-secret\n",
        encoding="utf-8",
    )
    return path

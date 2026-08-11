"""Failure ordering, cleanup, and concurrency tests for Stage 4C migration."""

from __future__ import annotations

from pathlib import Path

from configuration_migration_fakes import FakePreferenceStore, FakeSecretStore

from meeting_memory.repo.secret_store import SecretStoreCleanupUncertain
from meeting_memory.service import configuration_migration
from meeting_memory.service.configuration_migration import EnvironmentMigrationService
from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration import (
    SecretId,
    SecretRef,
)
from meeting_memory.types.configuration_migration import (
    MigrationConfirmation,
    MigrationOutcomeState,
    MigrationPreviewState,
)


def test_source_change_delete_replace_or_symlink_retarget_before_apply_writes_nothing(
    tmp_path: Path,
) -> None:
    for change in ("mutate", "replace", "retarget", "delete"):
        first = tmp_path / f"{change}.env"
        first.write_text("ASSEMBLYAI_API_KEY=first-secret\n", encoding="utf-8")
        env_path = first
        if change == "retarget":
            link = tmp_path / f"{change}.link"
            link.symlink_to(first)
            env_path = link
        preferences = FakePreferenceStore()
        secrets = FakeSecretStore()
        service = _service(env_path, preferences, secrets)
        preview = service.preview()
        assert preview.state is MigrationPreviewState.READY

        if change == "mutate":
            first.write_text("ASSEMBLYAI_API_KEY=other-secret\n", encoding="utf-8")
        elif change == "replace":
            replacement = tmp_path / "replacement.env"
            replacement.write_text("ASSEMBLYAI_API_KEY=first-secret\n", encoding="utf-8")
            replacement.replace(first)
        elif change == "retarget":
            other = tmp_path / "other.env"
            other.write_text("ASSEMBLYAI_API_KEY=first-secret\n", encoding="utf-8")
            env_path.unlink()
            env_path.symlink_to(other)
        else:
            first.unlink()

        outcome = service.apply(_confirmation(preview, Capability.TRANSCRIPTION))

        assert outcome.state is MigrationOutcomeState.STALE_SOURCE
        assert secrets.written == []
        assert preferences.cas_calls == []


def test_preference_change_before_writes_or_during_cas_cleans_only_new_refs(
    tmp_path: Path,
) -> None:
    env_path = _provider_env(tmp_path)
    preferences = FakePreferenceStore()
    secrets = FakeSecretStore()
    service = _service(env_path, preferences, secrets)
    preview = service.preview()
    preferences.change()

    before = service.apply(_confirmation(preview, Capability.TRANSCRIPTION))

    assert before.state is MigrationOutcomeState.PREFERENCES_CONFLICT
    assert secrets.written == []

    preferences = FakePreferenceStore()
    secrets = FakeSecretStore()
    service = _service(env_path, preferences, secrets)
    preview = service.preview()
    preferences.before_cas = preferences.change

    during = service.apply(_confirmation(preview, Capability.TRANSCRIPTION))

    assert during.state is MigrationOutcomeState.PREFERENCES_CONFLICT
    assert secrets.deleted == list(secrets.materials) or len(secrets.deleted) == 1
    assert secrets.materials == {}


def test_partial_keychain_failure_or_post_write_source_change_cleans_every_new_ref(
    tmp_path: Path,
) -> None:
    env_path = _provider_env(tmp_path)
    preferences = FakePreferenceStore()
    secrets = FakeSecretStore()
    secrets.fail_write_at = 1
    service = _service(env_path, preferences, secrets)
    preview = service.preview()

    failed = service.apply(_confirmation(preview, Capability.TRANSCRIPTION, Capability.NOTES))

    assert failed.state is MigrationOutcomeState.KEYCHAIN_FAILED
    assert len(secrets.written) == 1
    assert len(secrets.deleted) == 1
    assert preferences.cas_calls == []

    preferences = FakePreferenceStore()
    secrets = FakeSecretStore()
    service = _service(env_path, preferences, secrets)
    preview = service.preview()
    original = env_path.read_bytes()
    secrets.on_write = lambda _bundle: env_path.write_bytes(
        b"ASSEMBLYAI_API_KEY='unterminated\nsecret-sentinel"
    )

    stale = service.apply(_confirmation(preview, Capability.TRANSCRIPTION))

    assert stale.state is MigrationOutcomeState.STALE_SOURCE
    assert len(secrets.deleted) == 1
    assert preferences.cas_calls == []
    assert original != env_path.read_bytes()
    assert "secret-sentinel" not in repr(stale)


def test_unexpected_post_write_source_recheck_failure_is_sanitized_and_cleans(
    tmp_path: Path,
    monkeypatch,
) -> None:
    env_path = _provider_env(tmp_path)
    preferences = FakePreferenceStore()
    secrets = FakeSecretStore()
    service = _service(env_path, preferences, secrets)
    preview = service.preview()
    monkeypatch.setattr(
        configuration_migration,
        "source_matches",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("source-secret-sentinel")),
    )

    outcome = service.apply(_confirmation(preview, Capability.TRANSCRIPTION))

    assert outcome.state is MigrationOutcomeState.STALE_SOURCE
    assert secrets.materials == {}
    assert len(secrets.deleted) == 1
    assert preferences.cas_calls == []
    assert "source-secret-sentinel" not in repr(outcome)


def test_cleanup_failure_is_terminal_sanitized_and_continues_other_deletes(
    tmp_path: Path,
) -> None:
    env_path = _provider_env(tmp_path)
    preferences = FakePreferenceStore()
    secrets = FakeSecretStore()
    first = SecretRef(SecretId.TRANSCRIPTION, f"{1:032x}")
    secrets.fail_delete.add(first)
    secrets.fail_write_at = 2
    service = _service(env_path, preferences, secrets)
    preview = service.preview()

    outcome = service.apply(
        _confirmation(
            preview,
            Capability.TRANSCRIPTION,
            Capability.NOTES,
            Capability.BACKUP,
        )
    )

    assert outcome.state is MigrationOutcomeState.CLEANUP_FAILED
    assert len(secrets.deleted) == 2
    assert "sentinel" not in repr(outcome)
    assert preferences.cas_calls == []


def test_keychain_cleanup_uncertainty_cleans_prior_refs_and_never_activates(
    tmp_path: Path,
) -> None:
    env_path = _provider_env(tmp_path)
    preferences = FakePreferenceStore()

    class UncertainSecretStore(FakeSecretStore):
        def write_new(self, bundle):
            if self.written:
                raise SecretStoreCleanupUncertain("secret-sentinel")
            return super().write_new(bundle)

    secrets = UncertainSecretStore()
    service = _service(env_path, preferences, secrets)
    preview = service.preview()

    outcome = service.apply(_confirmation(preview, Capability.TRANSCRIPTION, Capability.NOTES))

    assert outcome.state is MigrationOutcomeState.CLEANUP_FAILED
    assert len(secrets.deleted) == 1
    assert secrets.materials == {}
    assert preferences.cas_calls == []
    assert "secret-sentinel" not in repr(outcome)


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
        "ASSEMBLYAI_API_KEY=assembly-secret\n"
        "ANTHROPIC_API_KEY=notes-secret\n"
        "B2_APPLICATION_KEY_ID=b2-id\n"
        "B2_APPLICATION_KEY=b2-secret\n"
        "B2_ENDPOINT=https://s3.example.invalid\n"
        "B2_REGION=region\n"
        "B2_BUCKET_NAME=bucket\n",
        encoding="utf-8",
    )
    return path

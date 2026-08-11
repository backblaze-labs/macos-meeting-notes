"""CAS visibility and secret-retention tests for Stage 4C migration."""

from __future__ import annotations

from pathlib import Path

import pytest
from configuration_migration_fakes import FakePreferenceStore, FakeSecretStore

from meeting_memory.service.configuration_migration import EnvironmentMigrationService
from meeting_memory.service.preference_store import (
    PreferencesDurabilityUncertain,
    PreferencesStoreError,
    snapshot_for_preferences,
)
from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration import (
    AppPreferences,
    PreferenceSnapshot,
    SecretId,
    SecretRef,
)
from meeting_memory.types.configuration_migration import (
    MigrationConfirmation,
    MigrationOutcomeState,
)


def test_durability_uncertain_requires_exact_visible_replacement_and_never_deletes(
    tmp_path: Path,
) -> None:
    env_path = _provider_env(tmp_path)
    preferences = FakePreferenceStore()
    preferences.durability_uncertain = True
    secrets = FakeSecretStore()
    service = _service(env_path, preferences, secrets)
    preview = service.preview()

    outcome = service.apply(_confirmation(preview))

    assert outcome.state is MigrationOutcomeState.DURABILITY_UNCERTAIN
    assert outcome.activated is True
    assert secrets.deleted == []

    preferences = FakePreferenceStore()
    preferences.durability_uncertain = True
    preferences.uncertain_snapshot = PreferenceSnapshot(AppPreferences(), "f" * 64)
    secrets = FakeSecretStore()
    service = _service(env_path, preferences, secrets)
    preview = service.preview()

    mismatch = service.apply(_confirmation(preview))

    assert mismatch.state is MigrationOutcomeState.DURABILITY_UNCERTAIN
    assert mismatch.activated is True
    assert secrets.deleted == []


def test_generic_cas_error_exact_replacement_or_precommit_is_classified_safely(
    tmp_path: Path,
) -> None:
    env_path = _provider_env(tmp_path)

    class LateGenericStore(FakePreferenceStore):
        def compare_and_swap(self, expected, replacement):
            super().compare_and_swap(expected, replacement)
            raise PreferencesStoreError("late generic sentinel")

    preferences = LateGenericStore()
    secrets = FakeSecretStore()
    service = _service(env_path, preferences, secrets)
    visible = service.apply(_confirmation(service.preview()))

    assert visible.state is MigrationOutcomeState.DURABILITY_UNCERTAIN
    active_ref = preferences.snapshot.preferences.secret_ref_for(SecretId.TRANSCRIPTION)
    assert active_ref in secrets.materials
    assert secrets.deleted == []

    preferences = FakePreferenceStore()
    preferences.cas_error = PreferencesStoreError("precommit generic sentinel")
    secrets = FakeSecretStore()
    service = _service(env_path, preferences, secrets)
    precommit = service.apply(_confirmation(service.preview()))

    assert precommit.state is MigrationOutcomeState.FAILED
    assert secrets.materials == {}
    assert len(secrets.deleted) == 1


def test_unreadable_or_mismatched_state_after_cas_error_retains_inactive_refs(
    tmp_path: Path,
) -> None:
    env_path = _provider_env(tmp_path)

    class UnreadableStore(FakePreferenceStore):
        def compare_and_swap(self, expected, replacement):
            self.load_error = PreferencesStoreError("reload sentinel")
            raise PreferencesStoreError("cas sentinel")

    preferences = UnreadableStore()
    secrets = FakeSecretStore()
    service = _service(env_path, preferences, secrets)
    unreadable = service.apply(_confirmation(service.preview()))

    assert unreadable.state is MigrationOutcomeState.ACTIVATION_UNCERTAIN
    assert len(secrets.materials) == 1
    assert secrets.deleted == []

    class OverwrittenStore(FakePreferenceStore):
        def compare_and_swap(self, expected, replacement):
            self.change(AppPreferences(secret_refs=(SecretRef(SecretId.NOTES, "d" * 32),)))
            raise PreferencesStoreError("overwrite sentinel")

    preferences = OverwrittenStore()
    secrets = FakeSecretStore()
    service = _service(env_path, preferences, secrets)
    overwritten = service.apply(_confirmation(service.preview()))

    assert overwritten.state is MigrationOutcomeState.ACTIVATION_UNCERTAIN
    assert len(secrets.materials) == 1
    assert secrets.deleted == []


def test_invalid_cas_return_uses_visible_state_classifier(tmp_path: Path) -> None:
    env_path = _provider_env(tmp_path)

    class InvalidReturnStore(FakePreferenceStore):
        def compare_and_swap(self, expected, replacement):
            super().compare_and_swap(expected, replacement)
            return object()

    preferences = InvalidReturnStore()
    secrets = FakeSecretStore()
    service = _service(env_path, preferences, secrets)
    outcome = service.apply(_confirmation(service.preview()))

    assert outcome.state is MigrationOutcomeState.DURABILITY_UNCERTAIN
    assert outcome.activated is True
    assert secrets.deleted == []


def test_nominal_cas_return_requires_exact_reload_proof(tmp_path: Path) -> None:
    env_path = _provider_env(tmp_path)

    class ReturnWithoutWriteStore(FakePreferenceStore):
        def compare_and_swap(self, expected, replacement):
            return PreferenceSnapshot(replacement, "b" * 64)

    preferences = ReturnWithoutWriteStore()
    secrets = FakeSecretStore()
    service = _service(env_path, preferences, secrets)
    missing = service.apply(_confirmation(service.preview()))

    assert missing.state is MigrationOutcomeState.FAILED
    assert secrets.materials == {}
    assert len(secrets.deleted) == 1

    class WrongReturnStore(FakePreferenceStore):
        def compare_and_swap(self, expected, replacement):
            visible = super().compare_and_swap(expected, replacement)
            return PreferenceSnapshot(replacement, "c" * 64) if visible else visible

    preferences = WrongReturnStore()
    secrets = FakeSecretStore()
    service = _service(env_path, preferences, secrets)
    mismatched = service.apply(_confirmation(service.preview()))

    assert mismatched.state is MigrationOutcomeState.DURABILITY_UNCERTAIN
    assert mismatched.activated is True
    assert secrets.deleted == []


@pytest.mark.parametrize("trigger", ["uncertainty", "invalid-return"])
@pytest.mark.parametrize(
    ("visible", "expected"),
    [
        ("intended", MigrationOutcomeState.DURABILITY_UNCERTAIN),
        ("unchanged", MigrationOutcomeState.FAILED),
        ("other", MigrationOutcomeState.ACTIVATION_UNCERTAIN),
    ],
)
def test_mismatched_cas_signals_share_the_exact_reload_matrix(
    tmp_path: Path,
    trigger: str,
    visible: str,
    expected: MigrationOutcomeState,
) -> None:
    class MatrixStore(FakePreferenceStore):
        def compare_and_swap(self, _bound, replacement):
            if visible == "intended":
                self.snapshot = snapshot_for_preferences(replacement)
            elif visible == "other":
                self.change(AppPreferences(secret_refs=(SecretRef(SecretId.NOTES, "d" * 32),)))
            if trigger == "uncertainty":
                raise PreferencesDurabilityUncertain(PreferenceSnapshot(AppPreferences(), "f" * 64))
            return object()

    preferences = MatrixStore()
    secrets = FakeSecretStore()
    service = _service(_provider_env(tmp_path), preferences, secrets)

    outcome = service.apply(_confirmation(service.preview()))

    assert outcome.state is expected
    if expected is MigrationOutcomeState.FAILED:
        assert secrets.materials == {}
        assert len(secrets.deleted) == 1
    else:
        assert len(secrets.materials) == 1
        assert secrets.deleted == []


def _service(path: Path, preferences, secrets) -> EnvironmentMigrationService:
    return EnvironmentMigrationService(
        path,
        preference_store=preferences,
        secret_store=secrets,
        id_factory=lambda: "a" * 32,
    )


def _confirmation(preview) -> MigrationConfirmation:
    return MigrationConfirmation(preview.preview_id, (Capability.TRANSCRIPTION,), True)


def _provider_env(tmp_path: Path) -> Path:
    path = tmp_path / ".env"
    path.write_text("ASSEMBLYAI_API_KEY=assembly-secret\n", encoding="utf-8")
    return path

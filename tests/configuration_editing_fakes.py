"""Shared in-memory adapters for configuration editing tests."""

from __future__ import annotations

from dataclasses import dataclass, field

from meeting_memory.service.configuration_editing import CapabilityConfigurationService
from meeting_memory.service.preference_store import (
    PreferencesConflictError,
    snapshot_for_preferences,
)
from meeting_memory.types.configuration import (
    AppPreferences,
    PreferenceSnapshot,
    SecretBundle,
    SecretId,
    SecretMaterial,
    SecretRef,
    SecretValue,
    SettingKey,
)


@dataclass
class FakePreferences:
    preferences: AppPreferences
    behavior: str = "success"
    cas_calls: int = 0
    operations: list[str] | None = None
    snapshot: PreferenceSnapshot = field(init=False)

    def __post_init__(self) -> None:
        self.snapshot = snapshot_for_preferences(self.preferences)

    def load_snapshot(self) -> PreferenceSnapshot:
        if self.behavior == "unknown" and self.cas_calls:
            raise RuntimeError("private-store-sentinel")
        return self.snapshot

    def compare_and_swap(self, expected, replacement) -> PreferenceSnapshot:
        self.cas_calls += 1
        if self.operations is not None:
            self.operations.append("preferences_cas")
        if self.behavior == "conflict":
            raise PreferencesConflictError("conflict")
        intended = snapshot_for_preferences(replacement)
        if self.behavior == "install_then_raise":
            self.snapshot = intended
            raise RuntimeError("private-store-sentinel")
        if self.behavior == "unknown":
            self.snapshot = PreferenceSnapshot(AppPreferences(), "e" * 64)
            raise RuntimeError("private-store-sentinel")
        assert expected == self.snapshot
        self.snapshot = intended
        return intended


@dataclass
class FakeSecrets:
    materials: dict[SecretRef, SecretMaterial] = field(default_factory=dict)
    reads: list[SecretRef] = field(default_factory=list)
    writes: list[SecretRef] = field(default_factory=list)
    deletes: list[SecretRef] = field(default_factory=list)
    returned_ref: SecretRef | None = None
    delete_fails_for: SecretRef | None = None
    operations: list[str] | None = None

    def read(self, ref: SecretRef) -> SecretMaterial | None:
        self.reads.append(ref)
        return self.materials.get(ref)

    def write_new(self, bundle: SecretBundle) -> SecretRef:
        if self.operations is not None:
            self.operations.append("secret_write")
        ref = self.returned_ref or SecretRef(
            bundle.secret_id,
            f"{len(self.writes) + 1:032x}",
        )
        self.writes.append(ref)
        return ref

    def delete(self, ref: SecretRef) -> None:
        if self.operations is not None:
            self.operations.append("secret_delete")
        self.deletes.append(ref)
        if ref == self.delete_fails_for:
            raise RuntimeError("private-delete-sentinel")


class IdFactory:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> str:
        self.value += 1
        return f"{self.value:032x}"


def service(
    preferences: AppPreferences | None = None,
    *,
    store: FakePreferences | None = None,
    secrets: FakeSecrets | None = None,
    process: dict[str, str] | None = None,
) -> CapabilityConfigurationService:
    return CapabilityConfigurationService(
        preference_store=store
        if store is not None
        else FakePreferences(preferences or AppPreferences()),
        secret_store=secrets if secrets is not None else FakeSecrets(),
        env_path=None,
        process_environment=process or {},
        id_factory=IdFactory(),
    )


def value(fields, key: SettingKey) -> str:
    return next(field.value.value for field in fields if field.key is key)


def transcription_bundle(value: str) -> SecretBundle:
    return SecretBundle(
        SecretId.TRANSCRIPTION,
        (SecretValue(SettingKey.ASSEMBLYAI_API_KEY, value),),
    )


def notes_bundle(value: str) -> SecretBundle:
    return SecretBundle(
        SecretId.NOTES,
        (SecretValue(SettingKey.ANTHROPIC_API_KEY, value),),
    )


def backup_bundle(key_id: str, key: str) -> SecretBundle:
    return SecretBundle(
        SecretId.BACKUP,
        (
            SecretValue(SettingKey.B2_APPLICATION_KEY_ID, key_id),
            SecretValue(SettingKey.B2_APPLICATION_KEY, key),
        ),
    )


def complete_legacy_backup() -> str:
    return "\n".join(
        (
            "B2_APPLICATION_KEY_ID=legacy-id",
            "B2_APPLICATION_KEY=legacy-secret",
            "B2_ENDPOINT=https://s3.example.com",
            "B2_REGION=us-west-004",
            "B2_BUCKET_NAME=legacy-bucket",
            "",
        )
    )

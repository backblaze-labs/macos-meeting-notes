"""In-memory Stage 4C stores; no real Keychain or user preferences."""

from __future__ import annotations

from collections.abc import Callable

from meeting_memory.service.preference_store import (
    PreferencesConflictError,
    PreferencesDurabilityUncertain,
    snapshot_for_preferences,
)
from meeting_memory.types.configuration import (
    AppPreferences,
    PreferenceSnapshot,
    SecretBundle,
    SecretMaterial,
    SecretRef,
)


class FakePreferenceStore:
    def __init__(self, preferences: AppPreferences = AppPreferences()) -> None:
        self.snapshot = PreferenceSnapshot(preferences, None)
        self.cas_calls: list[tuple[PreferenceSnapshot, AppPreferences]] = []
        self.load_error: Exception | None = None
        self.cas_error: Exception | None = None
        self.durability_uncertain = False
        self.uncertain_snapshot: PreferenceSnapshot | None = None
        self.before_cas: Callable[[], None] | None = None
        self._revision = 0

    def load_snapshot(self) -> PreferenceSnapshot:
        if self.load_error:
            raise self.load_error
        return self.snapshot

    def compare_and_swap(
        self,
        expected: PreferenceSnapshot,
        replacement: AppPreferences,
    ) -> PreferenceSnapshot:
        self.cas_calls.append((expected, replacement))
        if self.before_cas:
            self.before_cas()
        if self.cas_error:
            error = self.cas_error
            if isinstance(error, PreferencesDurabilityUncertain):
                self.snapshot = error.snapshot
            raise error
        if self.durability_uncertain:
            visible = snapshot_for_preferences(replacement)
            self.snapshot = visible
            raise PreferencesDurabilityUncertain(self.uncertain_snapshot or visible)
        if self.snapshot != expected:
            raise PreferencesConflictError("safe conflict")
        self.snapshot = snapshot_for_preferences(replacement)
        return self.snapshot

    def change(self, preferences: AppPreferences = AppPreferences()) -> None:
        self._revision += 1
        self.snapshot = PreferenceSnapshot(preferences, f"{self._revision:064x}")


class FakeSecretStore:
    def __init__(self) -> None:
        self.written: list[SecretBundle] = []
        self.deleted: list[SecretRef] = []
        self.materials: dict[SecretRef, SecretMaterial] = {}
        self.fail_write_at: int | None = None
        self.fail_delete: set[SecretRef] = set()
        self.on_write: Callable[[SecretBundle], None] | None = None
        self.return_ref: Callable[[SecretBundle, SecretRef], object] | None = None

    def write_new(self, bundle: SecretBundle) -> SecretRef:
        if self.fail_write_at == len(self.written):
            raise RuntimeError("secret write sentinel")
        self.written.append(bundle)
        ref = SecretRef(bundle.secret_id, f"{len(self.written):032x}")
        self.materials[ref] = SecretMaterial(ref, bundle)
        if self.on_write:
            self.on_write(bundle)
        return self.return_ref(bundle, ref) if self.return_ref else ref  # type: ignore[return-value]

    def delete(self, ref: SecretRef) -> None:
        self.deleted.append(ref)
        if ref in self.fail_delete:
            raise RuntimeError("secret delete sentinel")
        self.materials.pop(ref, None)

    def read(self, ref: SecretRef) -> SecretMaterial | None:
        return self.materials.get(ref)

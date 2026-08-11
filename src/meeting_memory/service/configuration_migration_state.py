"""Private state and storage boundaries for environment migration."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from meeting_memory.service.configuration_migration_source import (
    MigrationSourceFingerprint,
)
from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration import (
    AppPreferences,
    PreferenceSnapshot,
    SecretBundle,
    SecretRef,
)
from meeting_memory.types.configuration_migration import MigrationPreviewId


class MigrationPreferenceStore(Protocol):
    def load_snapshot(self) -> PreferenceSnapshot:
        raise NotImplementedError

    def compare_and_swap(
        self,
        expected: PreferenceSnapshot,
        replacement: AppPreferences,
    ) -> PreferenceSnapshot:
        raise NotImplementedError


class MigrationSecretStore(Protocol):
    def write_new(self, bundle: SecretBundle) -> SecretRef:
        raise NotImplementedError

    def delete(self, ref: SecretRef) -> None:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class MigrationPreviewBinding:
    """Private, secret-free binding for one single-use preview."""

    preview_id: MigrationPreviewId
    path: Path = field(repr=False)
    fingerprint: MigrationSourceFingerprint = field(repr=False)
    preferences: PreferenceSnapshot = field(repr=False)
    selectable: frozenset[Capability] = field(repr=False)


def valid_new_ref(
    ref: object,
    bundle: SecretBundle,
    created: list[SecretRef],
    snapshot: PreferenceSnapshot,
) -> bool:
    return (
        isinstance(ref, SecretRef)
        and ref.secret_id is bundle.secret_id
        and ref not in created
        and ref not in snapshot.preferences.secret_refs
    )

"""Inactive explicit, non-destructive legacy environment migration engine."""

from __future__ import annotations

import os
import threading
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path

from meeting_memory.config.runtime_layout import current_runtime_layout
from meeting_memory.repo.secret_store import (
    KeychainSecretStore,
    SecretStoreCleanupUncertain,
)
from meeting_memory.service.configuration_migration_cas import classify_cas_visibility
from meeting_memory.service.configuration_migration_outcomes import (
    migration_outcome,
    migration_preview_empty,
    migration_preview_failed,
)
from meeting_memory.service.configuration_migration_paths import migration_apply_plan
from meeting_memory.service.configuration_migration_plan import (
    MigrationPlan,
    build_migration_plan,
)
from meeting_memory.service.configuration_migration_source import (
    read_migration_source,
    source_matches,
)
from meeting_memory.service.configuration_migration_state import (
    MigrationPreferenceStore,
    MigrationPreviewBinding,
    MigrationSecretStore,
    valid_new_ref,
)
from meeting_memory.service.preference_store import (
    PreferencesConflictError,
    PreferencesDurabilityUncertain,
    PreferenceStore,
    snapshot_for_preferences,
)
from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration import (
    PreferenceSnapshot,
    SecretRef,
    SettingKey,
)
from meeting_memory.types.configuration_migration import (
    MigrationConfirmation,
    MigrationOutcome,
    MigrationOutcomeState,
    MigrationPreview,
    MigrationPreviewId,
    MigrationPreviewState,
)
from meeting_memory.types.runtime_layout import RuntimeLayout


class EnvironmentMigrationService:
    """Hold one private single-use preview and apply it only after confirmation."""

    __slots__ = (
        "_binding",
        "_env_path",
        "_id_factory",
        "_lock",
        "_preferences",
        "_runtime_layout",
        "_secrets",
    )

    def __init__(
        self,
        env_path: str | Path = ".env",
        *,
        preference_store: MigrationPreferenceStore | None = None,
        secret_store: MigrationSecretStore | None = None,
        id_factory: Callable[[], str] | None = None,
        runtime_layout: RuntimeLayout | None = None,
    ) -> None:
        self._runtime_layout = runtime_layout or current_runtime_layout()
        self._env_path = self._runtime_layout.legacy_source_path(env_path)
        self._preferences = (
            preference_store if preference_store is not None else PreferenceStore.default()
        )
        self._secrets = secret_store if secret_store is not None else KeychainSecretStore()
        self._id_factory = id_factory if id_factory is not None else lambda: uuid.uuid4().hex
        self._lock = threading.Lock()
        self._binding: MigrationPreviewBinding | None = None

    @property
    def requires_source_selection(self) -> bool:
        return self._env_path is None

    def preview(
        self,
        *,
        process_environment: Mapping[str, str] | None = None,
        source_path: str | Path | None = None,
    ) -> MigrationPreview:
        """Create a new preview, invalidating any earlier unconsumed preview."""

        with self._lock:
            self._binding = None
            try:
                preview_id = MigrationPreviewId(self._id_factory())
                process = os.environ if process_environment is None else process_environment
                process_names = frozenset(process.keys())
                process_keys = frozenset(key for key in SettingKey if key.value in process_names)
                env_path = (
                    self._env_path
                    if source_path is None
                    else self._runtime_layout.legacy_source_path(source_path)
                )
                if env_path is None:
                    raise ValueError("legacy source selection is required")
                source = read_migration_source(env_path)
            except Exception:
                preview_id = MigrationPreviewId("0" * 32)
                process_keys = frozenset()
                return migration_preview_failed(preview_id, process_keys)
            if source is None or not source.values:
                return migration_preview_empty(preview_id, process_keys)
            try:
                snapshot = self._preferences.load_snapshot()
                if not isinstance(snapshot, PreferenceSnapshot):
                    raise TypeError("invalid preference snapshot")
            except Exception:
                return migration_preview_failed(preview_id, process_keys)
            try:
                plan = build_migration_plan(source.values, snapshot.preferences, process_keys)
            except Exception:
                return migration_preview_failed(preview_id, process_keys)
            if not plan.selectable:
                return migration_preview_empty(preview_id, process_keys, plan.candidates)
            self._binding = MigrationPreviewBinding(
                preview_id,
                env_path,
                source.fingerprint,
                snapshot,
                frozenset(plan.selectable),
            )
            return MigrationPreview(
                preview_id,
                MigrationPreviewState.READY,
                plan.candidates,
                "Legacy configuration is available for explicit migration.",
                "Review the capability selection before confirming migration.",
            )

    def apply(self, confirmation: object) -> MigrationOutcome:
        """Consume one exact confirmation before performing any storage I/O."""

        if not isinstance(confirmation, MigrationConfirmation):
            return migration_outcome(MigrationOutcomeState.REJECTED, ())
        with self._lock:
            binding = self._binding
            if binding is None or binding.preview_id != confirmation.preview_id:
                return migration_outcome(MigrationOutcomeState.REJECTED, confirmation.selected)
            self._binding = None
        selected = confirmation.selected
        if confirmation.confirmed is not True or not set(selected) <= binding.selectable:
            return migration_outcome(MigrationOutcomeState.REJECTED, selected)
        try:
            source = read_migration_source(binding.path)
        except Exception:
            source = None
        if source is None or source.fingerprint != binding.fingerprint:
            return migration_outcome(MigrationOutcomeState.STALE_SOURCE, selected)
        try:
            current = self._preferences.load_snapshot()
        except Exception:
            return migration_outcome(MigrationOutcomeState.PREFERENCES_CONFLICT, selected)
        if not isinstance(current, PreferenceSnapshot) or current != binding.preferences:
            return migration_outcome(MigrationOutcomeState.PREFERENCES_CONFLICT, selected)
        try:
            plan = migration_apply_plan(
                source.values,
                current.preferences,
                selected,
                self._runtime_layout,
                binding.path,
            )
        except Exception:
            return migration_outcome(MigrationOutcomeState.FAILED, selected)
        if plan is None:
            return migration_outcome(MigrationOutcomeState.REJECTED, selected)
        return self._apply_plan(binding, plan, selected)

    def _apply_plan(
        self,
        binding: MigrationPreviewBinding,
        plan: MigrationPlan,
        selected: tuple[Capability, ...],
    ) -> MigrationOutcome:
        created: list[SecretRef] = []
        try:
            bundles = plan.secret_bundles(selected)
        except Exception:
            return migration_outcome(MigrationOutcomeState.FAILED, selected)
        for bundle in bundles:
            try:
                ref = self._secrets.write_new(bundle)
            except SecretStoreCleanupUncertain:
                return self._failure_with_cleanup(
                    MigrationOutcomeState.CLEANUP_FAILED,
                    selected,
                    created,
                )
            except Exception:
                return self._failure_with_cleanup(
                    MigrationOutcomeState.KEYCHAIN_FAILED,
                    selected,
                    created,
                )
            if not valid_new_ref(ref, bundle, created, binding.preferences):
                return self._failure_with_cleanup(
                    MigrationOutcomeState.CLEANUP_FAILED,
                    selected,
                    created,
                )
            created.append(ref)
        try:
            replacement = plan.replacement(selected, tuple(created))
            intended = snapshot_for_preferences(replacement)
        except Exception:
            return self._failure_with_cleanup(MigrationOutcomeState.FAILED, selected, created)
        try:
            unchanged = source_matches(binding.path, binding.fingerprint)
        except Exception:
            unchanged = False
        if not unchanged:
            return self._failure_with_cleanup(
                MigrationOutcomeState.STALE_SOURCE,
                selected,
                created,
            )
        try:
            saved = self._preferences.compare_and_swap(binding.preferences, replacement)
        except PreferencesDurabilityUncertain as error:
            if isinstance(error.snapshot, PreferenceSnapshot) and error.snapshot == intended:
                return migration_outcome(MigrationOutcomeState.DURABILITY_UNCERTAIN, selected)
            return self._classify_cas_error(binding, intended, selected, created)
        except PreferencesConflictError:
            return self._failure_with_cleanup(
                MigrationOutcomeState.PREFERENCES_CONFLICT,
                selected,
                created,
            )
        except Exception:
            return self._classify_cas_error(binding, intended, selected, created)
        if not isinstance(saved, PreferenceSnapshot) or saved != intended:
            return self._classify_cas_error(binding, intended, selected, created)
        return migration_outcome(MigrationOutcomeState.APPLIED, selected)

    def _classify_cas_error(
        self,
        binding: MigrationPreviewBinding,
        intended: PreferenceSnapshot,
        selected: tuple[Capability, ...],
        created: list[SecretRef],
    ) -> MigrationOutcome:
        state = classify_cas_visibility(
            self._preferences.load_snapshot,
            binding.preferences,
            intended,
        )
        if state is MigrationOutcomeState.FAILED:
            return self._failure_with_cleanup(state, selected, created)
        return migration_outcome(state, selected)

    def _failure_with_cleanup(
        self,
        state: MigrationOutcomeState,
        selected: tuple[Capability, ...],
        refs: list[SecretRef],
    ) -> MigrationOutcome:
        cleanup_failed = False
        for ref in refs:
            try:
                self._secrets.delete(ref)
            except Exception:
                cleanup_failed = True
        return migration_outcome(
            MigrationOutcomeState.CLEANUP_FAILED if cleanup_failed else state,
            selected,
        )

    def __repr__(self) -> str:
        return "EnvironmentMigrationService(source=<private>, binding=<private>)"

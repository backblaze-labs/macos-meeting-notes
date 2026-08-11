"""Worker-only coordinator for explicit native configuration actions."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path

from meeting_memory.config.settings import Settings
from meeting_memory.service.calendar_authorization import CalendarAuthorizationService
from meeting_memory.service.configuration_editing import CapabilityConfigurationService
from meeting_memory.service.configuration_migration import EnvironmentMigrationService
from meeting_memory.service.configuration_surface_operations import (
    apply_migration,
    authorize_calendar,
    failed_authorization,
    failed_configuration_save,
    failed_migration_apply,
    open_configuration,
    save_configuration,
    surface_is_busy,
)
from meeting_memory.service.configuration_surface_prompt import (
    failed_prompt_outcome,
    load_prompt,
    save_prompt,
)
from meeting_memory.service.runtime_capabilities import RuntimeCapabilityPause
from meeting_memory.service.summary_prompt import read_summary_prompt, write_summary_prompt
from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration_editing import (
    ConfigurationChange,
    ConfigurationOperationId,
)
from meeting_memory.types.configuration_migration import (
    MigrationConfirmation,
    MigrationPreviewId,
    MigrationPreviewState,
)
from meeting_memory.types.configuration_surface import (
    ConfigurationOpened,
    ConfigurationOpenFailed,
    MigrationPreviewed,
    MigrationPreviewFailed,
    PromptDraft,
    PromptLoaded,
    PromptOperationState,
    PromptSaved,
    SurfaceOperationKind,
)

EventSink = Callable[[object], None]
ThreadFactory = Callable[..., threading.Thread]


class ConfigurationSurfaceCoordinator:
    """Serialize bound operations and emit only safe, typed terminal events."""

    def __init__(
        self,
        event_sink: EventSink,
        *,
        configuration: CapabilityConfigurationService | None = None,
        migration: EnvironmentMigrationService | None = None,
        authorization: CalendarAuthorizationService | None = None,
        runtime_pause: RuntimeCapabilityPause | None = None,
        prompt_settings: Settings | None = None,
        prompt_reader: Callable[[Settings], str] = read_summary_prompt,
        prompt_writer: Callable[[Settings, str], Path] = write_summary_prompt,
        thread_factory: ThreadFactory = threading.Thread,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._sink = event_sink
        self._configuration = (
            configuration if configuration is not None else CapabilityConfigurationService()
        )
        self._migration = migration if migration is not None else EnvironmentMigrationService()
        self._authorization = (
            authorization if authorization is not None else CalendarAuthorizationService()
        )
        self._pause = runtime_pause if runtime_pause is not None else RuntimeCapabilityPause()
        self._prompt_settings = prompt_settings
        self._prompt_reader = prompt_reader
        self._prompt_writer = prompt_writer
        self._thread_factory = thread_factory
        self._id_factory = id_factory if id_factory is not None else lambda: uuid.uuid4().hex
        self._lock = threading.Lock()
        self._active: dict[SurfaceOperationKind, ConfigurationOperationId] = {}
        self._latest: dict[SurfaceOperationKind, ConfigurationOperationId] = {}
        self._drafts: dict[ConfigurationOperationId, PromptDraft] = {}
        self._bound_edit = None
        self._bound_preview: MigrationPreviewId | None = None
        self._bound_prompt: ConfigurationOperationId | None = None

    def open_configuration(self, capability: Capability) -> ConfigurationOperationId | None:
        kind = SurfaceOperationKind.CONFIGURATION
        with self._lock:
            if surface_is_busy(
                self._active, self._bound_edit, self._bound_preview, self._bound_prompt
            ):
                return None
            operation = self._reserve_locked(kind)
        return self._launch(
            kind,
            operation,
            lambda operation: open_configuration(self._configuration, operation, capability),
            lambda operation: ConfigurationOpenFailed(operation, capability),
        )

    def save_configuration(self, change: ConfigurationChange) -> ConfigurationOperationId | None:
        if not isinstance(change, ConfigurationChange):
            return None
        kind = SurfaceOperationKind.CONFIGURATION
        with self._lock:
            if kind in self._active or self._bound_edit != change.edit_id:
                return None
            self._bound_edit = None
            operation = self._reserve_locked(kind)
        return self._launch(
            kind,
            operation,
            lambda operation: save_configuration(
                self._configuration, self._pause, operation, change
            ),
            lambda operation: failed_configuration_save(operation, change.capability),
        )

    def cancel_configuration(self, edit_id) -> bool:
        with self._lock:
            if self._bound_edit != edit_id:
                return False
            self._bound_edit = None
            return True

    def preview_migration(
        self, process_environment: Mapping[str, str] | None = None
    ) -> ConfigurationOperationId | None:
        return self._start(
            SurfaceOperationKind.MIGRATION,
            lambda operation: MigrationPreviewed(
                operation,
                self._migration.preview(process_environment=process_environment),
            ),
            MigrationPreviewFailed,
        )

    def apply_migration(
        self, confirmation: MigrationConfirmation
    ) -> ConfigurationOperationId | None:
        if not isinstance(confirmation, MigrationConfirmation):
            return None
        kind = SurfaceOperationKind.MIGRATION
        with self._lock:
            if self._active or self._bound_preview != confirmation.preview_id:
                return None
            self._bound_preview = None
            operation = self._reserve_locked(kind)
        return self._launch(
            kind,
            operation,
            lambda operation: apply_migration(
                self._migration, self._pause, operation, confirmation
            ),
            lambda operation: failed_migration_apply(operation, confirmation),
        )

    def cancel_migration(self, preview_id: MigrationPreviewId) -> bool:
        with self._lock:
            if self._bound_preview != preview_id:
                return False
            self._bound_preview = None
            return True

    def authorize_calendar(self) -> ConfigurationOperationId | None:
        return self._start(
            SurfaceOperationKind.CALENDAR_AUTHORIZATION,
            lambda operation: authorize_calendar(self._authorization, operation),
            failed_authorization,
        )

    def load_prompt(self) -> ConfigurationOperationId | None:
        return self._start(
            SurfaceOperationKind.NOTES_PROMPT,
            self._load_prompt,
            lambda operation: PromptLoaded(operation, failed_prompt_outcome()),
        )

    def save_prompt(self, draft: PromptDraft) -> ConfigurationOperationId | None:
        if not isinstance(draft, PromptDraft):
            return None
        kind = SurfaceOperationKind.NOTES_PROMPT
        with self._lock:
            if self._active or self._bound_prompt is None:
                return None
            self._bound_prompt = None
            operation = self._reserve_locked(kind)
        return self._launch(
            kind,
            operation,
            lambda operation: self._save_prompt(operation, draft),
            lambda operation: PromptSaved(operation, failed_prompt_outcome()),
        )

    def cancel_prompt(self, operation: ConfigurationOperationId) -> bool:
        with self._lock:
            if self._bound_prompt != operation:
                return False
            self._bound_prompt = None
            self._drafts.pop(operation, None)
            return True

    def consume_prompt(self, operation: ConfigurationOperationId) -> PromptDraft | None:
        with self._lock:
            return self._drafts.pop(operation, None)

    def acknowledge(self, kind: SurfaceOperationKind, operation: ConfigurationOperationId) -> bool:
        with self._lock:
            if self._active.get(kind) != operation:
                return False
            self._active.pop(kind, None)
            return True

    def is_current(self, kind: SurfaceOperationKind, operation: ConfigurationOperationId) -> bool:
        with self._lock:
            return self._latest.get(kind) == operation

    def _start(
        self,
        kind: SurfaceOperationKind,
        work: Callable,
        failure: Callable,
    ) -> ConfigurationOperationId | None:
        with self._lock:
            if surface_is_busy(
                self._active, self._bound_edit, self._bound_preview, self._bound_prompt
            ):
                return None
            operation = self._reserve_locked(kind)
        return self._launch(kind, operation, work, failure)

    def _reserve_locked(self, kind):
        operation = ConfigurationOperationId(self._id_factory())
        self._active[kind] = operation
        self._latest[kind] = operation
        if kind is SurfaceOperationKind.NOTES_PROMPT:
            self._drafts.clear()
        return operation

    def _launch(self, kind, operation, work, failure):
        try:
            self._thread_factory(
                target=self._run,
                args=(kind, operation, work, failure),
                daemon=True,
            ).start()
        except Exception:
            self._sink(failure(operation))
        return operation

    def _run(self, kind, operation, work, failure) -> None:
        try:
            event = work(operation)
        except Exception:
            event = failure(operation)
        with self._lock:
            current = self._active.get(kind) == operation
            if current and isinstance(event, ConfigurationOpened):
                self._bound_edit = event.configuration.edit_id
            elif (
                current
                and isinstance(event, MigrationPreviewed)
                and event.preview.state is MigrationPreviewState.READY
            ):
                self._bound_preview = event.preview.preview_id
            elif (
                current
                and isinstance(event, PromptLoaded)
                and event.outcome.state is PromptOperationState.LOADED
            ):
                self._bound_prompt = operation
        if current and event is not None:
            self._sink(event)

    def _load_prompt(self, operation):
        event, draft = load_prompt(operation, self._prompt_settings, self._prompt_reader)
        if draft is not None:
            with self._lock:
                self._drafts.clear()
                self._drafts[operation] = draft
        return event

    def _save_prompt(self, operation, draft):
        return save_prompt(operation, self._prompt_settings, self._prompt_writer, draft)

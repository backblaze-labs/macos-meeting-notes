"""Worker coordination, stale-operation, and redaction tests for the native surface."""

from __future__ import annotations

from configuration_surface_fakes import (
    Authorization,
    Configuration,
    DeferredThread,
    FailingThread,
    IdFactory,
    ImmediateThread,
    Migration,
    Pause,
    SecondFailThread,
    configuration_view,
)

from meeting_memory.service.configuration_surface import ConfigurationSurfaceCoordinator
from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration import SettingKey
from meeting_memory.types.configuration_editing import (
    ConfigurationChange,
    ConfigurationSaveOutcome,
    ConfigurationSaveState,
)
from meeting_memory.types.configuration_migration import (
    MigrationCandidate,
    MigrationConfirmation,
    MigrationField,
    MigrationFieldState,
    MigrationOutcome,
    MigrationOutcomeState,
    MigrationPreview,
    MigrationPreviewId,
    MigrationPreviewState,
)
from meeting_memory.types.configuration_surface import (
    CalendarAuthorizationFinished,
    ConfigurationOpenFailed,
    ConfigurationSaved,
    MigrationApplied,
    MigrationPreviewFailed,
    PromptLoaded,
    SurfaceOperationKind,
)


def test_configuration_operations_are_globally_single_flight() -> None:
    DeferredThread.instances = []
    coordinator = _coordinator(thread_factory=DeferredThread)

    first = coordinator.open_configuration(Capability.BACKUP)
    second = coordinator.open_configuration(Capability.NOTES)

    assert first is not None
    assert second is None
    assert len(DeferredThread.instances) == 1


def test_surface_operations_are_single_flight_across_every_kind() -> None:
    DeferredThread.instances = []
    coordinator = _coordinator(thread_factory=DeferredThread)

    assert coordinator.open_configuration(Capability.BACKUP) is not None
    assert coordinator.preview_migration({}) is None
    assert coordinator.authorize_calendar() is None
    assert coordinator.load_prompt() is None
    assert len(DeferredThread.instances) == 1


def test_completed_open_holds_edit_binding_until_cancel() -> None:
    events: list[object] = []
    configuration = Configuration(open_result=configuration_view(Capability.NOTES))
    coordinator = _coordinator(event_sink=events.append, configuration=configuration)

    opened = coordinator.open_configuration(Capability.NOTES)
    assert opened is not None
    assert coordinator.acknowledge(SurfaceOperationKind.CONFIGURATION, opened)
    assert coordinator.open_configuration(Capability.BACKUP) is None
    assert coordinator.cancel_configuration(events[0].configuration.edit_id)
    assert coordinator.open_configuration(Capability.BACKUP) is not None


def test_save_pauses_before_emitting_terminal_event() -> None:
    order: list[str] = []
    outcome = ConfigurationSaveOutcome(
        ConfigurationSaveState.SAVED,
        Capability.BACKUP,
        "Saved.",
        "Restart.",
        pause_current_session=True,
    )
    view = configuration_view(Capability.BACKUP)
    coordinator = _coordinator(
        event_sink=lambda event: (
            order.append(type(event).__name__) if isinstance(event, ConfigurationSaved) else None
        ),
        configuration=Configuration(
            save_outcome=outcome,
            order=order,
            open_result=view,
        ),
        runtime_pause=Pause(order),
    )

    opened = coordinator.open_configuration(Capability.BACKUP)
    assert opened is not None
    coordinator.acknowledge(SurfaceOperationKind.CONFIGURATION, opened)
    coordinator.save_configuration(
        ConfigurationChange(view.edit_id, Capability.BACKUP, False, view.fields)
    )

    assert order == ["save", "pause:backup", "ConfigurationSaved"]


def test_migration_attempts_every_pause_before_event() -> None:
    order: list[str] = []
    selected = tuple(
        capability for capability in Capability if capability is not Capability.RECORDING_CORE
    )
    outcome = MigrationOutcome(
        MigrationOutcomeState.ACTIVATION_UNCERTAIN,
        selected,
        "Uncertain.",
        "Restart.",
    )
    events: list[object] = []
    preview = _migration_preview(MigrationPreviewId("a" * 32))
    coordinator = _coordinator(
        event_sink=events.append,
        migration=Migration(outcome, preview),
        runtime_pause=Pause(order, fail=Capability.TRANSCRIPTION),
    )
    preview_operation = coordinator.preview_migration({})
    assert preview_operation is not None
    assert coordinator.acknowledge(SurfaceOperationKind.MIGRATION, preview_operation)

    coordinator.apply_migration(MigrationConfirmation(preview.preview_id, selected, True))

    assert order == [
        "pause:transcription",
        "pause:backup",
        "pause:calendar",
        "pause:notes",
    ]
    assert isinstance(events[-1], MigrationApplied)
    assert events[-1].runtime_pause_succeeded is False


def test_thread_start_failure_emits_each_typed_terminal() -> None:
    events: list[object] = []
    _coordinator(event_sink=events.append, thread_factory=FailingThread).open_configuration(
        Capability.NOTES
    )
    view = configuration_view(Capability.NOTES)
    SecondFailThread.starts = 0
    save_coordinator = _coordinator(
        event_sink=events.append,
        thread_factory=SecondFailThread,
        configuration=Configuration(open_result=view),
    )
    opened = save_coordinator.open_configuration(Capability.NOTES)
    assert opened is not None
    save_coordinator.acknowledge(SurfaceOperationKind.CONFIGURATION, opened)
    events.pop()
    save_coordinator.save_configuration(
        ConfigurationChange(view.edit_id, Capability.NOTES, False, view.fields)
    )
    _coordinator(event_sink=events.append, thread_factory=FailingThread).preview_migration({})
    SecondFailThread.starts = 0
    migration_preview = _migration_preview(MigrationPreviewId("b" * 32))
    migration_coordinator = _coordinator(
        event_sink=events.append,
        thread_factory=SecondFailThread,
        migration=Migration(preview=migration_preview),
    )
    preview_operation = migration_coordinator.preview_migration({})
    assert preview_operation is not None
    assert migration_coordinator.acknowledge(SurfaceOperationKind.MIGRATION, preview_operation)
    events.pop()
    migration_coordinator.apply_migration(
        MigrationConfirmation(
            migration_preview.preview_id,
            (Capability.NOTES,),
            True,
        )
    )
    _coordinator(event_sink=events.append, thread_factory=FailingThread).authorize_calendar()
    _coordinator(event_sink=events.append, thread_factory=FailingThread).load_prompt()

    assert [type(event) for event in events] == [
        ConfigurationOpenFailed,
        ConfigurationSaved,
        MigrationPreviewFailed,
        MigrationApplied,
        CalendarAuthorizationFinished,
        PromptLoaded,
    ]
    assert "thread-sentinel" not in repr(events)


def test_latest_operation_helper_rejects_queued_old_completion() -> None:
    coordinator = _coordinator()
    old = coordinator.authorize_calendar()
    assert old is not None
    assert coordinator.acknowledge(SurfaceOperationKind.CALENDAR_AUTHORIZATION, old)
    new = coordinator.authorize_calendar()

    assert new is not None
    assert coordinator.is_current(SurfaceOperationKind.CALENDAR_AUTHORIZATION, old) is False
    assert coordinator.is_current(SurfaceOperationKind.CALENDAR_AUTHORIZATION, new) is True


def _coordinator(**overrides) -> ConfigurationSurfaceCoordinator:
    values = {
        "event_sink": lambda _event: None,
        "configuration": Configuration(),
        "migration": Migration(),
        "authorization": Authorization(),
        "runtime_pause": Pause([]),
        "prompt_settings": object(),
        "thread_factory": ImmediateThread,
        "id_factory": IdFactory(),
    }
    values.update(overrides)
    return ConfigurationSurfaceCoordinator(**values)


def _migration_preview(preview_id: MigrationPreviewId) -> MigrationPreview:
    candidates = tuple(
        MigrationCandidate(
            capability,
            (
                MigrationField(
                    capability,
                    SettingKey.ANTHROPIC_API_KEY,
                    MigrationFieldState.IMPORTABLE,
                    True,
                ),
            )
            if capability is Capability.NOTES
            else (),
            capability is Capability.NOTES,
        )
        for capability in Capability
    )
    return MigrationPreview(
        preview_id,
        MigrationPreviewState.READY,
        candidates,
        "Ready.",
        "Review.",
    )

"""Private prompt lifecycle and redacted event tests for the native surface."""

from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

import pytest
from configuration_surface_fakes import (
    Authorization,
    Configuration,
    FailingThread,
    IdFactory,
    ImmediateThread,
    Migration,
    Pause,
    SecondFailThread,
)

from meeting_memory.service.configuration_surface import ConfigurationSurfaceCoordinator
from meeting_memory.types.configuration_editing import ConfigurationOperationId
from meeting_memory.types.configuration_surface import (
    PromptDestination,
    PromptDraft,
    PromptLoaded,
    PromptOperationState,
    PromptOutcome,
    PromptSaved,
    SurfaceOperationKind,
)


def test_prompt_load_and_save_failures_have_matching_events() -> None:
    events: list[object] = []
    coordinator = _coordinator(
        event_sink=events.append,
        prompt_reader=lambda _settings: (_ for _ in ()).throw(RuntimeError("secret")),
    )
    coordinator.load_prompt()
    assert isinstance(events[0], PromptLoaded)
    assert events[0].outcome.state is PromptOperationState.FAILED
    assert "secret" not in repr(events)


@pytest.mark.parametrize("failure", ["reader", "thread"])
def test_new_prompt_operation_purges_stale_plaintext_after_failure(failure: str) -> None:
    events: list[object] = []
    coordinator = _coordinator(
        event_sink=events.append,
        prompt_reader=lambda _settings: "private prompt sentinel",
    )
    first = coordinator.load_prompt()
    assert first is not None
    assert coordinator.acknowledge(SurfaceOperationKind.NOTES_PROMPT, first)
    assert coordinator.cancel_prompt(first)
    if failure == "reader":
        coordinator._prompt_reader = lambda _settings: (_ for _ in ()).throw(  # noqa: SLF001
            RuntimeError("reader-sentinel")
        )
    else:
        coordinator._thread_factory = FailingThread  # noqa: SLF001

    second = coordinator.load_prompt()

    assert second is not None
    assert coordinator.consume_prompt(first) is None
    assert coordinator.consume_prompt(second) is None
    assert "private prompt sentinel" not in repr(events)


def test_prompt_draft_is_immutable_and_never_enters_event_graph() -> None:
    events: list[object] = []
    coordinator = _coordinator(
        event_sink=events.append,
        prompt_reader=lambda _settings: "private prompt sentinel",
    )

    operation = coordinator.load_prompt()
    assert operation is not None
    draft = coordinator.consume_prompt(operation)

    assert draft is not None and draft.text == "private prompt sentinel"
    assert deepcopy(draft) is draft
    assert "sentinel" not in repr(draft)
    assert "sentinel" not in repr(asdict(events[0]))
    with pytest.raises(AttributeError):
        draft._text = "changed"  # type: ignore[misc]


def test_prompt_destination_is_ui_readable_but_redacted_in_event_graph() -> None:
    events: list[object] = []
    destination = Path("/private/path-sentinel/prompt.md")
    coordinator = _coordinator(
        event_sink=events.append,
        prompt_writer=lambda *_args: destination,
    )
    operation = _bind_prompt(coordinator, events)

    coordinator.save_prompt(PromptDraft("private prompt"))

    event = events[-1]
    assert isinstance(event, PromptSaved)
    assert event.outcome.destination is not None
    assert event.outcome.destination.value == str(destination)
    assert "path-sentinel" not in repr(event)
    assert "path-sentinel" not in repr(asdict(event))
    assert coordinator.consume_prompt(operation) is None


def test_surface_events_reject_untyped_ids_payloads_and_invalid_prompt_states() -> None:
    operation = ConfigurationOperationId("e" * 32)
    with pytest.raises(ValueError, match="operation"):
        PromptLoaded("not-an-id", _loaded())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="payload"):
        PromptLoaded(operation, object())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="terminal state"):
        PromptSaved(operation, _loaded())
    with pytest.raises(ValueError, match="destination"):
        PromptOutcome(PromptOperationState.SAVED, "Saved.", "Next.")
    with pytest.raises(ValueError, match="safe path"):
        PromptDestination(Path("bad\npath"))


def test_untyped_prompt_writer_result_is_a_sanitized_failure() -> None:
    class PrivateResult:
        def __str__(self) -> str:
            return "private-writer-sentinel"

    events: list[object] = []
    coordinator = _coordinator(
        event_sink=events.append,
        prompt_writer=lambda *_args: PrivateResult(),
    )
    _bind_prompt(coordinator, events)

    coordinator.save_prompt(PromptDraft("private prompt"))

    event = events[-1]
    assert isinstance(event, PromptSaved)
    assert event.outcome.state is PromptOperationState.FAILED
    assert event.outcome.destination is None
    assert "private-writer-sentinel" not in repr(event)


def test_prompt_save_thread_failure_emits_typed_terminal() -> None:
    events: list[object] = []
    SecondFailThread.starts = 0
    coordinator = _coordinator(event_sink=events.append, thread_factory=SecondFailThread)
    _bind_prompt(coordinator, events)

    coordinator.save_prompt(PromptDraft("private"))

    assert isinstance(events[-1], PromptSaved)
    assert events[-1].outcome.state is PromptOperationState.FAILED


def _bind_prompt(coordinator, events) -> ConfigurationOperationId:
    operation = coordinator.load_prompt()
    assert operation is not None
    assert coordinator.acknowledge(SurfaceOperationKind.NOTES_PROMPT, operation)
    assert coordinator.consume_prompt(operation) is not None
    events.clear()
    return operation


def _loaded() -> PromptOutcome:
    return PromptOutcome(PromptOperationState.LOADED, "Loaded.", "Review.")


def _coordinator(**overrides) -> ConfigurationSurfaceCoordinator:
    values = {
        "event_sink": lambda _event: None,
        "configuration": Configuration(),
        "migration": Migration(),
        "authorization": Authorization(),
        "runtime_pause": Pause([]),
        "prompt_settings": object(),
        "prompt_reader": lambda _settings: "prompt",
        "thread_factory": ImmediateThread,
        "id_factory": IdFactory(),
    }
    values.update(overrides)
    return ConfigurationSurfaceCoordinator(**values)

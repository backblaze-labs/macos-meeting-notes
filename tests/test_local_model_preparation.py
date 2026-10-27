"""Explicit worker preparation, cancellation, and sanitized failure contracts."""

from configuration_surface_fakes import DeferredThread, ImmediateThread

from meeting_memory.service.local_model_preparation import LocalModelPreparationCoordinator
from meeting_memory.types.local_model_preparation import LocalModelState
from meeting_memory.types.local_transcription import (
    LocalBackendStatus,
    LocalModelProgress,
    LocalTranscriptionError,
)

MISSING = LocalBackendStatus(True, True, False, "Models need preparation.", "Choose Prepare.")
READY = LocalBackendStatus(True, True, True, "Models are ready.", "")


def test_construction_performs_no_inspection_or_download() -> None:
    def explode(**_kwargs):
        raise AssertionError("unexpected startup I/O")

    coordinator = LocalModelPreparationCoordinator([], inspect=explode, prepare=explode)
    assert not coordinator.busy


def test_explicit_check_never_prepares_and_emits_status() -> None:
    events = []
    coordinator = LocalModelPreparationCoordinator(
        events.append,
        inspect=lambda: MISSING,
        prepare=lambda **_: (_ for _ in ()).throw(AssertionError("download")),
        thread_factory=ImmediateThread,
    )
    operation = coordinator.check()
    assert operation is not None
    assert events[-1].state is LocalModelState.AVAILABLE
    assert events[-1].status == MISSING
    assert not coordinator.busy


def test_preparation_progress_is_measured_only_when_adapter_supplies_bytes() -> None:
    events = []

    def prepare(*, progress, cancelled):
        assert not cancelled()
        progress(LocalModelProgress("downloading", "Downloading weights.", 25, 100))

    coordinator = LocalModelPreparationCoordinator(
        events.append, inspect=lambda: READY, prepare=prepare, thread_factory=ImmediateThread
    )
    coordinator.prepare()
    progress = next(event.progress for event in events if event.progress)
    assert (progress.completed_bytes, progress.total_bytes) == (25, 100)
    assert events[-1].state is LocalModelState.READY
    assert not coordinator.busy


def test_single_flight_cancel_prevents_queued_preparation() -> None:
    DeferredThread.instances.clear()
    events, calls = [], []
    coordinator = LocalModelPreparationCoordinator(
        events.append,
        inspect=lambda: READY,
        prepare=lambda **_: calls.append("prepare"),
        thread_factory=DeferredThread,
    )
    operation = coordinator.prepare()
    assert coordinator.prepare() is None
    assert coordinator.check() is None
    assert coordinator.cancel()
    DeferredThread.instances[-1].target(*DeferredThread.instances[-1].args)
    assert calls == []
    assert events[-1].operation_id == operation
    assert events[-1].state is LocalModelState.CANCELLED
    assert not coordinator.busy


def test_known_failure_has_recovery_unknown_failure_is_redacted() -> None:
    for error, expected in (
        (LocalTranscriptionError("Disk is full.", "Free space and choose Retry."), "Disk is full."),
        (RuntimeError("secret-sentinel"), "Local model preparation could not finish."),
    ):
        events = []

        def prepare(**_kwargs):
            raise error

        coordinator = LocalModelPreparationCoordinator(
            events.append, inspect=lambda: MISSING, prepare=prepare, thread_factory=ImmediateThread
        )
        coordinator.prepare()
        assert events[-1].state is LocalModelState.FAILED
        assert events[-1].summary == expected
        assert events[-1].action
        assert "secret-sentinel" not in repr(events)


def test_shutdown_cancels_joins_bounded_and_rejects_future_operations():
    class JoinableThread(DeferredThread):
        def join(self, *, timeout):
            self.timeout = timeout
            self.target(*self.args)

    JoinableThread.instances.clear()
    calls, events = [], []
    coordinator = LocalModelPreparationCoordinator(
        events.append,
        inspect=lambda: READY,
        prepare=lambda **_: calls.append("prepare"),
        thread_factory=JoinableThread,
        shutdown_timeout=0.25,
    )
    coordinator.prepare()
    coordinator.shutdown()
    coordinator.shutdown()
    assert JoinableThread.instances[-1].timeout == 0.25
    assert calls == []
    assert events[-1].state is LocalModelState.CANCELLED
    assert coordinator.check() is None and coordinator.prepare() is None


def test_shutdown_cancels_a_running_worker_and_waits_for_its_exit():
    import threading

    started, finished = threading.Event(), threading.Event()

    def prepare(*, cancelled, progress):
        started.set()
        while not cancelled():
            finished.wait(0.001)
        finished.set()

    coordinator = LocalModelPreparationCoordinator(
        lambda _: None,
        inspect=lambda: READY,
        prepare=prepare,
        shutdown_timeout=1,
    )
    coordinator.prepare()
    assert started.wait(1)
    coordinator.shutdown()
    assert finished.is_set() and not coordinator.busy
    assert coordinator.prepare() is None


def test_default_inspection_passes_worker_cancellation_to_metal_probe(monkeypatch):
    captured = []

    def inspect(*, probe_metal, cancelled):
        assert probe_metal
        captured.append(cancelled)
        return READY

    monkeypatch.setattr("meeting_memory.repo.local_models.inspect_local_backend", inspect)
    coordinator = LocalModelPreparationCoordinator(
        lambda _: None,
        thread_factory=ImmediateThread,
    )
    coordinator.check()
    assert len(captured) == 1 and not captured[0]()
    coordinator.shutdown()
    assert captured[0]()

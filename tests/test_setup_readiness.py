"""Thread and UI boundaries for explicit readiness checks."""

from __future__ import annotations

import queue
from types import SimpleNamespace

import pytest
from tray_fakes import FakeRumps

from meeting_memory.types.capabilities import (
    Capability,
    CapabilityState,
    CapabilityStatus,
    ReadinessReport,
)
from meeting_memory.types.events import ReadinessChecked
from meeting_memory.ui import menu
from meeting_memory.ui.setup_readiness import ReadinessCheck
from meeting_memory.ui.tray import RumpsTrayApp


def test_exact_report_is_loaded_off_thread_and_emitted_as_typed_event() -> None:
    report = _report()
    events: list[object] = []
    loads = 0
    thread = DeferredThread()

    def load_report() -> ReadinessReport:
        nonlocal loads
        loads += 1
        return report

    check = ReadinessCheck(
        events.append,
        report_loader=load_report,
        thread_factory=lambda **kwargs: thread.configure(**kwargs),
    )

    check.start()
    assert loads == 0
    assert events == []

    thread.run()
    assert loads == 1
    assert len(events) == 1
    assert isinstance(events[0], ReadinessChecked)
    assert events[0].report is report


def test_exact_background_report_is_the_one_rendered_by_the_tray() -> None:
    report = _report()
    events: list[object] = []
    check = ReadinessCheck(
        events.append,
        report_loader=lambda: report,
        thread_factory=ImmediateThread,
    )
    app = RumpsTrayApp(FakeController(), rumps_module=FakeRumps())

    check.start()
    app.handle_event(events[0])

    assert app.readiness_report is report
    debugging = next(
        item for item in app.app.menu.items if item and item.title == menu.DEBUGGING_LABEL
    )
    titles = [item.title for item in debugging.items if item is not None]
    assert [f"{capability.label}: Ready" for capability in Capability] == [
        title for title in titles if title.endswith(": Ready")
    ]


@pytest.mark.parametrize("failure", ["start", "load"])
def test_readiness_failures_emit_a_terminal_sanitized_report(failure: str) -> None:
    events: list[object] = []

    def fail_load() -> ReadinessReport:
        raise RuntimeError("secret diagnostic detail")

    check = ReadinessCheck(
        events.append,
        report_loader=fail_load if failure == "load" else _report,
        thread_factory=FailingStartThread if failure == "start" else ImmediateThread,
    )

    check.start()

    assert len(events) == 1
    assert isinstance(events[0], ReadinessChecked)
    assert all(status.state is CapabilityState.FAILED for status in events[0].report.statuses)
    visible = " ".join(status.summary for status in events[0].report.statuses)
    assert "secret diagnostic detail" not in visible


def test_repeated_check_is_single_flight_and_cannot_overwrite_with_stale_result() -> None:
    events: list[object] = []
    threads = ThreadCollector()
    check = ReadinessCheck(events.append, report_loader=_report, thread_factory=threads)

    check.start()
    check.start()

    assert len(threads.items) == 1
    threads.items[0].run()
    assert len(events) == 1

    check.start()
    assert len(threads.items) == 2


class ImmediateThread:
    def __init__(self, *, target, daemon=False):
        self.target = target
        self.daemon = daemon

    def start(self) -> None:
        self.target()


class FailingStartThread(ImmediateThread):
    def start(self) -> None:
        raise RuntimeError("thread backend detail")


class FakeController:
    def __init__(self) -> None:
        self.event_queue: queue.Queue[object] = queue.Queue()
        self.recorder = SimpleNamespace(is_recording=False, capture_mode="full-meeting")
        self.settings = SimpleNamespace()

    def recording_duration_seconds(self) -> int:
        return 0

    def recent_meetings(self) -> list[object]:
        return []

    def pending_processing_tasks(self) -> list[object]:
        return []

    def recovered_recordings(self) -> list[object]:
        return []

    def __getattr__(self, _name):
        return lambda *_args, **_kwargs: None


class DeferredThread:
    target = None

    def configure(self, *, target, daemon=False):
        self.target = target
        self.daemon = daemon
        return self

    def start(self) -> None:
        pass

    def run(self) -> None:
        assert self.target is not None
        self.target()


class ThreadCollector:
    def __init__(self) -> None:
        self.items: list[DeferredThread] = []

    def __call__(self, **kwargs):
        thread = DeferredThread().configure(**kwargs)
        self.items.append(thread)
        return thread


def _report() -> ReadinessReport:
    return ReadinessReport(
        tuple(
            CapabilityStatus(capability, CapabilityState.READY, "Ready.")
            for capability in Capability
        )
    )

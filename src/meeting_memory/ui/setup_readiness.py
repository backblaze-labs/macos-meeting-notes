"""Background readiness checks and compact UI rendering."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

from meeting_memory.service.readiness import failed_readiness_report, load_readiness_report
from meeting_memory.types.capabilities import CapabilityStatus, ReadinessReport
from meeting_memory.types.events import ReadinessChecked

LOGGER = logging.getLogger(__name__)
EventSink = Callable[[object], None]
ReportLoader = Callable[[], ReadinessReport]
ThreadFactory = Callable[..., threading.Thread]


@dataclass
class ReadinessCheck:
    """Run explicit setup diagnostics away from the UI thread."""

    event_sink: EventSink
    report_loader: ReportLoader = load_readiness_report
    thread_factory: ThreadFactory = threading.Thread
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _running: bool = field(default=False, init=False, repr=False)

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
        try:
            self.thread_factory(target=self._run, daemon=True).start()
        except Exception:
            LOGGER.exception("Could not start readiness worker")
            self._emit_and_finish(failed_readiness_report())

    def _run(self) -> None:
        try:
            report = self.report_loader()
        except Exception:
            LOGGER.exception("Readiness worker failed")
            report = failed_readiness_report()
        self._emit_and_finish(report)

    def _emit_and_finish(self, report: ReadinessReport) -> None:
        try:
            self.event_sink(ReadinessChecked(report))
        finally:
            self._finish()

    def _finish(self) -> None:
        with self._lock:
            self._running = False


def readiness_menu_label(status: CapabilityStatus) -> str:
    state = status.state.value.replace("_", " ").title()
    return f"{status.capability.label}: {state}"


def readiness_tooltip(status: CapabilityStatus) -> str:
    if status.action:
        return f"{status.summary} Action: {status.action}"
    return status.summary


def readiness_notification_body(report: ReadinessReport) -> str:
    return "; ".join(
        f"{status.capability.label}: {status.state.value}" for status in report.statuses
    )

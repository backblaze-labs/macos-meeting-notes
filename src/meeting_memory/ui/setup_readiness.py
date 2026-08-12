"""Background readiness checks and compact UI rendering."""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from meeting_memory.service.readiness import failed_readiness_report, load_readiness_report
from meeting_memory.types.capabilities import CapabilityStatus, ReadinessReport
from meeting_memory.types.configuration_editing import ConfigurationOperationId
from meeting_memory.types.events import ReadinessChecked

LOGGER = logging.getLogger(__name__)
EventSink = Callable[[object], None]
ReportLoader = Callable[[], ReadinessReport]
ThreadFactory = Callable[..., threading.Thread]


def readiness_loader_for(recorder: object) -> ReportLoader:
    """Bind a readiness check to the recorder's currently selected mode."""

    return lambda: load_readiness_report(capture_mode=getattr(recorder, "capture_mode"))


def readiness_check_for(controller: object) -> ReadinessCheck:
    """Create a mode-aware check for a tray controller."""

    return ReadinessCheck(
        getattr(controller, "event_queue").put,
        readiness_loader_for(getattr(controller, "recorder")),
    )


@dataclass
class ReadinessCheck:
    """Run explicit setup diagnostics away from the UI thread."""

    event_sink: EventSink
    report_loader: ReportLoader = load_readiness_report
    thread_factory: ThreadFactory = threading.Thread
    id_factory: Callable[[], str] = lambda: uuid.uuid4().hex
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _active: ConfigurationOperationId | None = field(default=None, init=False, repr=False)

    def start(self) -> ConfigurationOperationId | None:
        with self._lock:
            if self._active is not None:
                return None
            operation = ConfigurationOperationId(self.id_factory())
            self._active = operation
        try:
            self.thread_factory(target=self._run, args=(operation,), daemon=True).start()
        except Exception:
            LOGGER.error("Could not start readiness worker")
            self.event_sink(ReadinessChecked(operation, failed_readiness_report()))
        return operation

    def acknowledge(self, operation: ConfigurationOperationId) -> bool:
        with self._lock:
            if self._active != operation:
                return False
            self._active = None
            return True

    def _run(self, operation: ConfigurationOperationId) -> None:
        try:
            report = self.report_loader()
        except Exception:
            LOGGER.error("Readiness worker failed")
            report = failed_readiness_report()
        self.event_sink(ReadinessChecked(operation, report))


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

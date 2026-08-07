"""Surface asynchronous native-capture failures through the UI event queue."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from meeting_memory.types.events import NotifyEvent

LOGGER = logging.getLogger(__name__)
ThreadFactory = Callable[..., threading.Thread]


class RecordingHealthMonitor:
    def __init__(
        self,
        recorder: Any,
        event_queue: Any,
        *,
        thread_factory: ThreadFactory = threading.Thread,
    ) -> None:
        self._recorder = recorder
        self._event_queue = event_queue
        self._thread_factory = thread_factory
        self._lock = threading.Lock()
        self._in_flight = False

    def poll(self) -> None:
        if not getattr(self._recorder, "is_recording", False):
            return
        if getattr(self._recorder, "check_health", None) is None:
            return
        with self._lock:
            if self._in_flight:
                return
            self._in_flight = True
        worker = self._thread_factory(target=self._check, daemon=True)
        try:
            worker.start()
        except Exception:
            with self._lock:
                self._in_flight = False
            raise

    def _check(self) -> None:
        try:
            self._recorder.check_health()
        except Exception as exc:
            LOGGER.exception("Native recording stopped unexpectedly")
            self._event_queue.put(
                NotifyEvent(
                    title="Recording stopped unexpectedly",
                    body=str(exc).strip() or exc.__class__.__name__,
                )
            )
        finally:
            with self._lock:
                self._in_flight = False

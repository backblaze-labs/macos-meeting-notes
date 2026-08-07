"""Single-flight background transitions for tray recording controls."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal

from meeting_memory.service.recorder import RecordingResult
from meeting_memory.types.events import NotifyEvent
from meeting_memory.types.meeting import RecordingContext

LOGGER = logging.getLogger(__name__)
TransitionKind = Literal["start", "stop"]
ThreadFactory = Callable[..., threading.Thread]
ContextProvider = Callable[[], RecordingContext | None]
StartedCallback = Callable[[str, datetime | None], None]
StoppedCallback = Callable[[RecordingResult], None]


class RecordingTransitions:
    def __init__(
        self,
        recorder: Any,
        event_queue: Any,
        *,
        context_provider: ContextProvider,
        on_started: StartedCallback,
        on_stopped: StoppedCallback,
        thread_factory: ThreadFactory = threading.Thread,
    ) -> None:
        self._recorder = recorder
        self._event_queue = event_queue
        self._context_provider = context_provider
        self._on_started = on_started
        self._on_stopped = on_stopped
        self._thread_factory = thread_factory
        self._lock = threading.Lock()
        self._active: TransitionKind | None = None
        self._stop_after_start = False
        self._start_has_recording = False

    def request_start(
        self,
        calendar_title: str | None = None,
        *,
        ends_at: datetime | None = None,
        speaker_candidates: tuple[str, ...] = (),
    ) -> bool:
        return self._request(
            "start",
            lambda: self._start(calendar_title, ends_at, speaker_candidates),
        )

    def request_stop(self) -> bool:
        return self._request("stop", self._stop)

    def _request(self, kind: TransitionKind, action: Callable[[], None]) -> bool:
        with self._lock:
            if self._active is not None:
                if kind == "stop" and self._active == "start":
                    if self._stop_after_start:
                        return False
                    self._stop_after_start = True
                    return True
                return False
            self._active = kind

        return self._launch(kind, action)

    def _launch(self, kind: TransitionKind, action: Callable[[], None]) -> bool:
        try:
            worker = self._thread_factory(
                target=self._run,
                args=(kind, action),
                daemon=True,
            )
            worker.start()
        except Exception as exc:
            self._reset(kind)
            self._report_failure(kind, exc)
            return False
        return True

    def _run(self, kind: TransitionKind, action: Callable[[], None]) -> None:
        try:
            action()
        except Exception as exc:
            LOGGER.exception("Recording %s transition failed", kind)
            if kind == "start" and self._has_started_recording():
                self._event_queue.put(
                    NotifyEvent(
                        title="Recording setup failed",
                        body=(
                            f"{str(exc).strip() or exc.__class__.__name__}. "
                            "Stopping safely."
                        ),
                    )
                )
                self._stop_after_setup_failure()
            else:
                self._report_failure(kind, exc)
        finally:
            launch_stop = self._finish(kind)
            if launch_stop:
                self._launch("stop", self._stop)

    def _finish(self, kind: TransitionKind) -> bool:
        with self._lock:
            if self._active != kind:
                return False
            self._active = None
            should_stop = (
                kind == "start" and self._stop_after_start and self._start_has_recording
            )
            if kind == "start":
                self._stop_after_start = False
                self._start_has_recording = False
            if not should_stop:
                return False
            self._active = "stop"
            return True

    def _start(
        self,
        calendar_title: str | None,
        ends_at: datetime | None,
        speaker_candidates: tuple[str, ...],
    ) -> None:
        context = self._context_provider() if calendar_title is None and ends_at is None else None
        title = calendar_title or (context.calendar_title if context else "Untitled")
        reminder_end = ends_at or (context.ends_at if context else None)
        candidates = speaker_candidates or (context.speaker_candidates if context else ())
        session = self._recorder.start(calendar_title=title, speaker_candidates=candidates)
        has_recording = session is not None or bool(
            getattr(self._recorder, "is_recording", False)
        )
        if has_recording:
            with self._lock:
                self._start_has_recording = True
        if session is not None:
            self._on_started(title, reminder_end)

    def _stop(self) -> None:
        result = self._recorder.stop()
        if result is not None:
            self._on_stopped(result)

    def _reset(self, kind: TransitionKind) -> None:
        with self._lock:
            if self._active == kind:
                self._active = None
                if kind == "start":
                    self._stop_after_start = False
                    self._start_has_recording = False

    def _has_started_recording(self) -> bool:
        with self._lock:
            return self._start_has_recording

    def _queue_stop_after_start(self) -> None:
        with self._lock:
            if self._active == "start":
                self._stop_after_start = True

    def _stop_after_setup_failure(self) -> None:
        try:
            self._stop()
        except Exception as exc:
            LOGGER.exception("Could not stop after recording setup failed")
            self._report_failure("stop", exc)
        finally:
            with self._lock:
                self._stop_after_start = False
                self._start_has_recording = False

    def _report_failure(self, kind: TransitionKind, exc: Exception) -> None:
        title = "Recording could not start" if kind == "start" else "Recording could not finish"
        self._event_queue.put(
            NotifyEvent(
                title=title,
                body=str(exc).strip() or exc.__class__.__name__,
            )
        )

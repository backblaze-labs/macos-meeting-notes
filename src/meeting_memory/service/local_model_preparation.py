"""Single-flight explicit preparation with main-thread-only UI event delivery."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable

from meeting_memory.types.local_model_preparation import LocalModelState, LocalModelsUpdated
from meeting_memory.types.local_transcription import (
    LocalBackendStatus,
    LocalTranscriptionCancelled,
    LocalTranscriptionError,
)


class LocalModelPreparationCoordinator:
    def __init__(
        self,
        event_sink: Callable[[object], None],
        *,
        inspect=None,
        prepare=None,
        thread_factory=threading.Thread,
        shutdown_timeout: float = 2.0,
    ) -> None:
        self._emit = event_sink
        self._inspect = inspect
        self._prepare = prepare or _prepare
        self._thread_factory = thread_factory
        self._lock = threading.RLock()
        self._closed = False
        self._worker = None
        self._shutdown_timeout = max(0.0, shutdown_timeout)
        self._active = False
        self._operation_id = None
        self._cancelled = threading.Event()

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._active

    def is_current(self, operation_id: str) -> bool:
        with self._lock:
            return operation_id == self._operation_id

    def check(self) -> str | None:
        return self._start(False)

    def prepare(self) -> str | None:
        return self._start(True)

    def cancel(self) -> bool:
        with self._lock:
            if not self._active:
                return False
            self._cancelled.set()
            return True

    def shutdown(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._cancelled.set()
            worker = self._worker
        join = getattr(worker, "join", None)
        if callable(join) and worker is not threading.current_thread():
            try:
                join(timeout=self._shutdown_timeout)
            except RuntimeError:
                pass  # A reserved thread may not have started yet. It will see cancellation.

    def _start(self, preparing: bool) -> str | None:
        with self._lock:
            if self._active or self._closed:
                return None
            self._active = True
            operation_id = uuid.uuid4().hex
            self._operation_id = operation_id
            self._cancelled = threading.Event()
            cancelled = self._cancelled
        state = LocalModelState.PREPARING if preparing else LocalModelState.CHECKING
        self._emit(LocalModelsUpdated(operation_id, state, "Checking local models."))
        try:
            worker = self._thread_factory(
                target=self._run, args=(operation_id, preparing, cancelled), daemon=True
            )
            with self._lock:
                self._worker = worker
            worker.start()
        except Exception:
            self._finish(
                operation_id,
                LocalModelState.FAILED,
                "Local model preparation could not start.",
                "Close other dialogs and choose Retry.",
            )
        return operation_id

    def _run(self, operation_id: str, preparing: bool, cancelled: threading.Event) -> None:
        try:
            if cancelled.is_set():
                raise LocalTranscriptionCancelled()
            if preparing:

                def progress(value):
                    self._emit(
                        LocalModelsUpdated(
                            operation_id, LocalModelState.PREPARING, value.message, progress=value
                        )
                    )

                self._prepare(progress=progress, cancelled=cancelled.is_set)
            if cancelled.is_set():
                raise LocalTranscriptionCancelled()
            status = (
                self._inspect()
                if self._inspect is not None
                else _inspect(cancelled=cancelled.is_set)
            )
            if cancelled.is_set():
                raise LocalTranscriptionCancelled()
            if preparing and not status.models_ready:
                raise LocalTranscriptionError(status.summary, status.action)
            self._finish(
                operation_id,
                LocalModelState.READY if preparing else LocalModelState.AVAILABLE,
                status.summary,
                status.action,
                status,
            )
        except LocalTranscriptionCancelled:
            self._finish(
                operation_id,
                LocalModelState.CANCELLED,
                "Local model preparation was cancelled.",
                "Shared model files are preserved. Choose Retry when ready.",
            )
        except LocalTranscriptionError as error:
            self._finish(operation_id, LocalModelState.FAILED, str(error), error.action)
        except Exception:
            self._finish(
                operation_id,
                LocalModelState.FAILED,
                "Local model preparation could not finish.",
                "Check free disk space and network access, then choose Retry.",
            )

    def _finish(
        self, operation_id, state, summary, action, status: LocalBackendStatus | None = None
    ):
        with self._lock:
            if operation_id == self._operation_id:
                self._active = False
        self._emit(LocalModelsUpdated(operation_id, state, summary, action, status))


def _inspect(*, cancelled):
    from meeting_memory.repo.local_models import inspect_local_backend

    return inspect_local_backend(probe_metal=True, cancelled=cancelled)


def _prepare(**kwargs):
    from meeting_memory.repo.local_models import prepare_models

    return prepare_models(**kwargs)

"""Monotonic current-session pause boundary for optional capability egress."""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping

from meeting_memory.types.capabilities import Capability

PauseCallback = Callable[[], None]


class RuntimeCapabilityPause:
    """Pause new optional work; callbacks may let one in-flight request finish."""

    def __init__(self, callbacks: Mapping[Capability, PauseCallback] | None = None) -> None:
        self._callbacks = dict(callbacks or {})
        self._paused: set[Capability] = set()
        self._completed: set[Capability] = set()
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._pausing: set[Capability] = set()

    def register(self, capability: Capability, callback: PauseCallback) -> None:
        if capability is Capability.RECORDING_CORE:
            return
        with self._condition:
            self._callbacks[capability] = callback

    def pause(self, capability: Capability) -> bool:
        if capability is Capability.RECORDING_CORE:
            return True
        with self._condition:
            while capability in self._pausing:
                self._condition.wait()
            if capability in self._completed:
                return True
            self._paused.add(capability)
            self._pausing.add(capability)
            callback = self._callbacks.get(capability)
        succeeded = True
        try:
            if callback is not None:
                callback()
        except Exception:
            succeeded = False
        with self._condition:
            self._pausing.discard(capability)
            if succeeded:
                self._completed.add(capability)
            self._condition.notify_all()
        return succeeded

    def is_paused(self, capability: Capability) -> bool:
        with self._lock:
            return capability in self._paused

    def allows(self, capability: Capability) -> bool:
        return not self.is_paused(capability)

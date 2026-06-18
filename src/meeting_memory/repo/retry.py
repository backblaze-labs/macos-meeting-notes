"""Retry helpers for external repository adapters."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TypeVar

T = TypeVar("T")

DEFAULT_RETRY_DELAYS = (2.0, 4.0, 8.0)
TRANSIENT_STATUS_CODES = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
TRANSIENT_NAME_MARKERS = (
    "connecterror",
    "connection",
    "internalserver",
    "ratelimit",
    "rate_limit",
    "serviceunavailable",
    "temporar",
    "timeout",
    "toomanyrequests",
)


@dataclass(frozen=True)
class RetryPolicy:
    """Small, injectable retry policy for SDK calls."""

    delays: tuple[float, ...] = DEFAULT_RETRY_DELAYS
    sleeper: Callable[[float], None] = field(default=time.sleep, repr=False, compare=False)
    clock: Callable[[], float] = field(default=time.monotonic, repr=False, compare=False)
    timeout_seconds: float | None = None

    def call(
        self,
        operation: Callable[[], T],
        *,
        is_retryable: Callable[[BaseException], bool] | None = None,
        timeout_message: str = "operation timed out before retry",
    ) -> T:
        retryable = is_retryable or is_likely_transient_error
        deadline = self._deadline()
        for delay in (*self.delays, None):
            self._raise_if_expired(deadline, timeout_message)
            try:
                return operation()
            except Exception as exc:
                if delay is None or not retryable(exc):
                    raise
                self._raise_if_expired(deadline, timeout_message, cause=exc)
                self.sleeper(self._bounded_delay(delay, deadline, timeout_message, exc))

        raise RuntimeError("unreachable retry state")

    def _deadline(self) -> float | None:
        if self.timeout_seconds is None:
            return None
        return self.clock() + self.timeout_seconds

    def _raise_if_expired(
        self,
        deadline: float | None,
        message: str,
        cause: BaseException | None = None,
    ) -> None:
        if deadline is None or self.clock() < deadline:
            return
        raise TimeoutError(message) from cause

    def _bounded_delay(
        self,
        delay: float,
        deadline: float | None,
        message: str,
        cause: BaseException,
    ) -> float:
        if deadline is None:
            return delay
        remaining = deadline - self.clock()
        if remaining <= 0:
            raise TimeoutError(message) from cause
        return min(delay, remaining)


def is_likely_transient_error(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError | ConnectionError):
        return True

    status_code = _status_code(exc)
    if status_code in TRANSIENT_STATUS_CODES:
        return True

    name = exc.__class__.__name__.lower().replace("_", "")
    return any(marker in name for marker in TRANSIENT_NAME_MARKERS)


def _status_code(exc: BaseException) -> int | None:
    value = getattr(exc, "status_code", None)
    if value is None:
        response = getattr(exc, "response", None)
        value = getattr(response, "status_code", None)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

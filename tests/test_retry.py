"""Tests for repository retry helpers."""

from __future__ import annotations

import pytest

from meeting_memory.repo.retry import RetryPolicy, is_likely_transient_error


def test_retry_policy_retries_retryable_errors() -> None:
    attempts = 0
    sleeps: list[float] = []

    def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TimeoutError("temporary timeout")
        return "ok"

    result = RetryPolicy(delays=(0.1,), sleeper=sleeps.append).call(operation)

    assert result == "ok"
    assert attempts == 2
    assert sleeps == [0.1]


def test_retry_policy_honors_timeout_before_retry() -> None:
    ticks = iter((0.0, 0.0, 2.0))

    def operation() -> str:
        raise TimeoutError("temporary timeout")

    with pytest.raises(TimeoutError, match="operation timed out"):
        RetryPolicy(
            delays=(1.0,),
            sleeper=lambda _: None,
            clock=lambda: next(ticks),
            timeout_seconds=1.0,
        ).call(operation)


def test_is_likely_transient_error_accepts_status_codes() -> None:
    class ApiError(RuntimeError):
        status_code = 503

    assert is_likely_transient_error(ApiError("service unavailable")) is True
    assert is_likely_transient_error(ValueError("bad payload")) is False

"""Application-level error logging coverage."""

from __future__ import annotations

import logging
import sys

from meeting_memory import logging_config


def test_uncaught_exception_is_written_to_the_application_logger(caplog) -> None:
    try:
        raise RuntimeError("test failure")
    except RuntimeError:
        exc_type, _, _ = sys.exc_info()

    with caplog.at_level(logging.CRITICAL, logger="meeting_memory.logging_config"):
        logging_config._log_uncaught_exception("test thread", exc_type, None, None)

    assert caplog.records[0].message == (
        "Uncaught application exception in test thread error_type=RuntimeError"
    )
    assert caplog.records[0].exc_info is None


def test_normal_exit_exceptions_are_not_reported_as_application_errors(caplog) -> None:
    logging_config._log_uncaught_exception("test thread", SystemExit, SystemExit(), None)

    assert caplog.records == []

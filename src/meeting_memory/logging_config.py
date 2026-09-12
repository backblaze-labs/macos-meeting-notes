"""Logging setup for meeting-memory."""

from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path

LOG_DIR = Path.home() / "Library" / "Logs" / "meeting-memory"
LOG_FILE = LOG_DIR / "app.log"
LOGGER = logging.getLogger(__name__)
_EXCEPTION_HOOKS_INSTALLED = False


def configure_logging(level: int = logging.INFO) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=LOG_FILE,
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    _install_exception_logging()


def _install_exception_logging() -> None:
    global _EXCEPTION_HOOKS_INSTALLED
    if _EXCEPTION_HOOKS_INSTALLED:
        return
    _EXCEPTION_HOOKS_INSTALLED = True
    system_hook = sys.excepthook
    thread_hook = threading.excepthook

    def report_system_exception(exc_type, exc_value, traceback) -> None:
        _log_uncaught_exception("main thread", exc_type, exc_value, traceback)
        system_hook(exc_type, exc_value, traceback)

    def report_thread_exception(args: threading.ExceptHookArgs) -> None:
        origin = f"thread {args.thread.name}" if args.thread is not None else "thread"
        _log_uncaught_exception(origin, args.exc_type, args.exc_value, args.exc_traceback)
        thread_hook(args)

    sys.excepthook = report_system_exception
    threading.excepthook = report_thread_exception


def _log_uncaught_exception(origin, exc_type, exc_value, traceback) -> None:
    if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
        return
    LOGGER.critical(
        "Uncaught application exception in %s error_type=%s",
        origin,
        exc_type.__name__,
    )

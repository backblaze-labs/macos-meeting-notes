"""One bounded shutdown path for menu, Cocoa termination, and SIGTERM."""

from __future__ import annotations

import logging
import os
import signal
import threading

LOGGER = logging.getLogger(__name__)


class LocalShutdown:
    def __init__(
        self,
        quit_application,
        prepare_shutdown,
        runtime_shutdown=lambda: None,
        *,
        native=True,
        observe=None,
        signals=signal,
        terminate=None,
    ):
        self._quit_application = quit_application
        self._callbacks = (prepare_shutdown, runtime_shutdown)
        self._native = native
        self._observe = observe or _observe_termination
        self._signals = signals
        self._terminate = terminate or _terminate_process
        self._lock = threading.RLock()
        self._stopped = False
        self._quit_requested = False

    def stop(self, *_args):
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
        for callback in self._callbacks:
            try:
                callback()
            except Exception as error:
                LOGGER.error("Local shutdown callback failed error_type=%s", type(error).__name__)

    def quit(self, _sender=None):
        self.stop()
        with self._lock:
            if self._quit_requested:
                return
            self._quit_requested = True
        self._quit_application()

    def run(self, app_run):
        remove_observer = None
        previous = None
        installed = False
        try:
            if self._native:
                remove_observer = self._observe(self.stop)
                previous = self._signals.getsignal(signal.SIGTERM)
                self._signals.signal(signal.SIGTERM, self._sigterm)
                installed = True
            return app_run()
        finally:
            self.stop()
            if remove_observer is not None:
                remove_observer()
            if installed:
                self._signals.signal(signal.SIGTERM, previous)

    def _sigterm(self, signum, _frame):
        self.stop()
        # Terminate this process after bounded cleanup even if Cocoa is no longer pumping events.
        self._terminate(signum)


def _observe_termination(callback):
    from AppKit import NSApplicationWillTerminateNotification
    from Foundation import NSNotificationCenter

    center = NSNotificationCenter.defaultCenter()
    observer = center.addObserverForName_object_queue_usingBlock_(
        NSApplicationWillTerminateNotification, None, None, lambda _notification: callback()
    )
    return lambda: center.removeObserver_(observer)


def _terminate_process(signum):
    signal.signal(signum, signal.SIG_DFL)
    os.kill(os.getpid(), signum)

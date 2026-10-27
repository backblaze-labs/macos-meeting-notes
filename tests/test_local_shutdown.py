"""Menu, Cocoa quit, SIGTERM, and normal exit share bounded local cleanup."""

import signal
from types import SimpleNamespace

import pytest
from tray_fakes import FakeRumps

from meeting_memory.ui.local_shutdown import LocalShutdown, _observe_termination, _terminate_process
from meeting_memory.ui.setup_tray import RumpsSetupApp


class Signals:
    def __init__(self):
        self.handler = None
        self.restored = None

    def getsignal(self, signum):
        assert signum == signal.SIGTERM
        return "previous"

    def signal(self, signum, handler):
        assert signum == signal.SIGTERM
        if handler == "previous":
            self.restored = handler
        else:
            self.handler = handler


def test_quit_stops_both_workers_before_quitting_exactly_once():
    calls = []
    lifecycle = LocalShutdown(
        lambda: calls.append("quit"),
        lambda: calls.append("prepare"),
        lambda: calls.append("runtime"),
        native=False,
    )
    lifecycle.quit()
    lifecycle.quit()
    lifecycle.stop()
    assert calls == ["prepare", "runtime", "quit"]


def test_cocoa_sigterm_and_finally_use_same_idempotent_cleanup():
    calls, observers = [], []
    signals = Signals()

    def observe(callback):
        observers.append(callback)
        return lambda: calls.append("remove-observer")

    lifecycle = LocalShutdown(
        lambda: calls.append("quit"),
        lambda: calls.append("prepare"),
        lambda: calls.append("runtime"),
        observe=observe,
        signals=signals,
        terminate=lambda signum: calls.append(("terminate", signum)),
    )

    def app_run():
        observers[0]()
        signals.handler(signal.SIGTERM, None)
        return "result"

    assert lifecycle.run(app_run) == "result"
    assert calls == ["prepare", "runtime", ("terminate", signal.SIGTERM), "remove-observer"]
    assert signals.restored == "previous"


def test_normal_run_error_still_cleans_up_and_restores_hooks():
    calls = []
    signals = Signals()
    lifecycle = LocalShutdown(
        lambda: None,
        lambda: calls.append("prepare"),
        lambda: calls.append("runtime"),
        observe=lambda _: lambda: calls.append("remove"),
        signals=signals,
    )
    with pytest.raises(ValueError):
        lifecycle.run(lambda: (_ for _ in ()).throw(ValueError("app")))
    assert calls == ["prepare", "runtime", "remove"]
    assert signals.restored == "previous"


def test_cleanup_failure_does_not_skip_runtime_stop():
    calls = []
    lifecycle = LocalShutdown(
        lambda: calls.append("quit"),
        lambda: (_ for _ in ()).throw(RuntimeError("private-sentinel")),
        lambda: calls.append("runtime"),
        native=False,
    )
    lifecycle.quit()
    assert calls == ["runtime", "quit"]


def test_cocoa_observer_uses_app_termination_notification(monkeypatch):
    callbacks, removed = [], []
    center = SimpleNamespace(
        addObserverForName_object_queue_usingBlock_=lambda name, obj, queue, block: (
            callbacks.append((name, obj, queue, block)) or "token"
        ),
        removeObserver_=removed.append,
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "AppKit",
        SimpleNamespace(NSApplicationWillTerminateNotification="app-termination"),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "Foundation",
        SimpleNamespace(NSNotificationCenter=SimpleNamespace(defaultCenter=lambda: center)),
    )
    calls = []
    remove = _observe_termination(lambda: calls.append("stop"))
    assert callbacks[0][:3] == ("app-termination", None, None)
    callbacks[0][3](object())
    remove()
    assert calls == ["stop"] and removed == ["token"]


def test_sigterm_fallback_only_signals_own_process(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "meeting_memory.ui.local_shutdown.signal.signal",
        lambda signum, handler: calls.append((signum, handler)),
    )
    monkeypatch.setattr("meeting_memory.ui.local_shutdown.os.getpid", lambda: 12345)
    monkeypatch.setattr(
        "meeting_memory.ui.local_shutdown.os.kill", lambda pid, signum: calls.append((pid, signum))
    )
    _terminate_process(signal.SIGTERM)
    assert calls == [(signal.SIGTERM, signal.SIG_DFL), (12345, signal.SIGTERM)]


def test_setup_quit_menu_cleans_up_models_and_runtime():
    calls = []
    rumps = FakeRumps()
    rumps.quit_application = lambda: calls.append("quit")
    app = RumpsSetupApp(
        rumps_module=rumps,
        local_model_preparation=SimpleNamespace(shutdown=lambda: calls.append("models")),
        shutdown_callback=lambda: calls.append("runtime"),
    )
    quit_item = next(item for item in app.app.menu.items if item and item.title == "Quit")
    quit_item.callback(None)
    quit_item.callback(None)
    assert calls == ["models", "runtime", "quit"]


def test_runtime_quit_menu_and_run_finally_share_cleanup(tmp_path, monkeypatch):
    import queue

    from test_tray import FakePipeline, FakeRecorder, _settings

    from meeting_memory.ui.controller import TrayController
    from meeting_memory.ui.tray import RumpsTrayApp

    calls = []
    rumps = FakeRumps()
    rumps.quit_application = lambda: calls.append("quit")
    controller = TrayController(
        settings=_settings(tmp_path),
        recorder=FakeRecorder(tmp_path),
        pipeline=FakePipeline(),
        event_queue=queue.Queue(),
    )
    app = RumpsTrayApp(
        controller,
        rumps_module=rumps,
        local_model_preparation=SimpleNamespace(shutdown=lambda: calls.append("models")),
        shutdown_callback=lambda: calls.append("runtime"),
    )
    app.people_base.startup = lambda: None
    monkeypatch.setattr(
        "meeting_memory.ui.tray.keep_timer_running_during_menu_tracking", lambda *_: None
    )
    quit_item = next(item for item in app.app.menu.items if item and item.title == "Quit")
    app.app.run = lambda: quit_item.callback(None)
    app.run()
    assert calls == ["models", "runtime", "quit"]

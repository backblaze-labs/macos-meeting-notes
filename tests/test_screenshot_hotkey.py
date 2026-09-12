"""Tests for the Carbon-backed global screenshot hotkey."""

from __future__ import annotations

import ctypes
import logging

from meeting_memory.ui.screenshot_hotkey import (
    DEFAULT_KEY_CODE,
    DEFAULT_MODIFIERS,
    HOT_KEY_PRESSED,
    KEYBOARD_EVENT_CLASS,
    GlobalHotkey,
)


class FakeFunction:
    def __init__(self, result=0, recorder=None):
        self.result = result
        self.recorder = recorder
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)
        if self.recorder is not None:
            self.recorder(*args)
        return self.result


class FakeCarbon:
    def __init__(self, register_status=0):
        self.handler = None
        self.spec = None
        self.GetApplicationEventTarget = FakeFunction(result=42)
        self.InstallEventHandler = FakeFunction(recorder=self._install)
        self.RegisterEventHotKey = FakeFunction(result=register_status)
        self.UnregisterEventHotKey = FakeFunction()
        self.RemoveEventHandler = FakeFunction()

    def _install(self, _target, handler, count, spec_ref, _user_data, _handler_ref) -> None:
        self.handler = handler
        self.spec = spec_ref._obj
        assert count == 1


def test_install_registers_the_default_shortcut_and_dispatches_presses() -> None:
    presses: list[str] = []
    carbon = FakeCarbon()
    hotkey = GlobalHotkey(lambda: presses.append("shot"), library_loader=lambda: carbon)

    assert hotkey.install() is True
    assert hotkey.installed is True
    assert carbon.spec.eventClass == KEYBOARD_EVENT_CLASS
    assert carbon.spec.eventKind == HOT_KEY_PRESSED
    key_code, modifiers, hotkey_id, target, options, _ref = carbon.RegisterEventHotKey.calls[0]
    assert (key_code, modifiers, target, options) == (DEFAULT_KEY_CODE, DEFAULT_MODIFIERS, 42, 0)
    assert hotkey_id.id == 1

    assert carbon.handler(None, None, None) == 0
    assert presses == ["shot"]


def test_install_reports_failures_without_raising(caplog) -> None:
    carbon = FakeCarbon(register_status=-9868)
    hotkey = GlobalHotkey(
        lambda: None, library_loader=lambda: carbon, logger=logging.getLogger("t")
    )

    with caplog.at_level(logging.WARNING, logger="t"):
        assert hotkey.install() is False

    assert hotkey.installed is False
    assert "unavailable" in caplog.text

    def missing():
        raise OSError("no Carbon")

    assert GlobalHotkey(lambda: None, library_loader=missing).install() is False


def test_callback_errors_do_not_escape_the_carbon_handler() -> None:
    carbon = FakeCarbon()

    def boom() -> None:
        raise RuntimeError("capture failed")

    hotkey = GlobalHotkey(boom, library_loader=lambda: carbon)
    hotkey.install()

    assert carbon.handler(None, None, None) == 0


def test_uninstall_releases_the_registration() -> None:
    carbon = FakeCarbon()
    hotkey = GlobalHotkey(lambda: None, library_loader=lambda: carbon)
    hotkey.install()

    hotkey.uninstall()

    assert hotkey.installed is False
    assert len(carbon.UnregisterEventHotKey.calls) == 1
    assert len(carbon.RemoveEventHandler.calls) == 1
    assert isinstance(carbon.RemoveEventHandler.calls[0][0], ctypes.c_void_p)

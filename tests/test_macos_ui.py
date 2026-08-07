"""Tests for macOS UI integration helpers."""

from __future__ import annotations

import sys
import types

from meeting_memory.ui.macos import (
    allow_foreground_notifications,
    hide_dock_icon_when_app_activates,
    keep_timer_running_during_menu_tracking,
)


def test_allow_foreground_notifications_installs_delegate_method(monkeypatch) -> None:
    class FakeNSApp:
        @classmethod
        def instancesRespondToSelector_(cls, _selector):
            return False

    fake_foundation = types.SimpleNamespace(NSSelectorFromString=lambda value: value)
    fake_rumps = types.SimpleNamespace(rumps=types.SimpleNamespace(NSApp=FakeNSApp))
    monkeypatch.setitem(sys.modules, "Foundation", fake_foundation)
    monkeypatch.setitem(sys.modules, "rumps", fake_rumps)
    monkeypatch.setitem(sys.modules, "rumps.rumps", fake_rumps.rumps)

    allow_foreground_notifications(types.SimpleNamespace(debug=lambda *args, **kwargs: None))

    method = FakeNSApp.userNotificationCenter_shouldPresentNotification_
    assert method(None, None, None) is True


def test_hide_dock_icon_when_app_activates_installs_delegate_method(monkeypatch) -> None:
    calls = []

    class FakeNSApp:
        @classmethod
        def instancesRespondToSelector_(cls, _selector):
            return False

    class FakeNSApplication:
        @staticmethod
        def sharedApplication():
            return FakeNSApplication()

        def setActivationPolicy_(self, policy):
            calls.append(policy)

    fake_foundation = types.SimpleNamespace(NSSelectorFromString=lambda value: value)
    fake_rumps = types.SimpleNamespace(rumps=types.SimpleNamespace(NSApp=FakeNSApp))
    fake_appkit = types.SimpleNamespace(
        NSApplication=FakeNSApplication,
        NSApplicationActivationPolicyAccessory="accessory",
    )
    monkeypatch.setitem(sys.modules, "Foundation", fake_foundation)
    monkeypatch.setitem(sys.modules, "rumps", fake_rumps)
    monkeypatch.setitem(sys.modules, "rumps.rumps", fake_rumps.rumps)
    monkeypatch.setitem(sys.modules, "AppKit", fake_appkit)

    hide_dock_icon_when_app_activates(
        types.SimpleNamespace(debug=lambda *args, **kwargs: None)
    )

    FakeNSApp.applicationDidBecomeActive_(None, None)
    assert calls == ["accessory"]


def test_keep_timer_running_during_menu_tracking_uses_appkit_mode(monkeypatch) -> None:
    added_modes = []

    class FakeRunLoop:
        def addTimer_forMode_(self, ns_timer, mode) -> None:
            added_modes.append((ns_timer, mode))

    class FakeNSRunLoop:
        @staticmethod
        def currentRunLoop():
            return FakeRunLoop()

    fake_appkit = types.SimpleNamespace(
        NSEventTrackingRunLoopMode="NSEventTrackingRunLoopMode"
    )
    fake_foundation = types.SimpleNamespace(
        NSRunLoop=FakeNSRunLoop,
        NSRunLoopCommonModes="NSRunLoopCommonModes",
    )
    fake_timer = types.SimpleNamespace(_nstimer="native-timer")
    monkeypatch.setitem(sys.modules, "AppKit", fake_appkit)
    monkeypatch.setitem(sys.modules, "Foundation", fake_foundation)

    keep_timer_running_during_menu_tracking(
        fake_timer,
        types.SimpleNamespace(debug=lambda *args, **kwargs: None),
    )

    assert added_modes == [
        ("native-timer", "NSRunLoopCommonModes"),
        ("native-timer", "NSEventTrackingRunLoopMode"),
    ]

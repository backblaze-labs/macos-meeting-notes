"""Tests for macOS UI integration helpers."""

from __future__ import annotations

import sys
import types

from meeting_memory.ui.macos import allow_foreground_notifications


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

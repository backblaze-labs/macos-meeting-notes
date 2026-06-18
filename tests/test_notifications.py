"""Tests for notification delivery selection."""

from __future__ import annotations

import logging
import types

from meeting_memory.ui import notifications


def test_send_notification_uses_direct_delivery_for_real_rumps(monkeypatch) -> None:
    calls = []

    def fake_deliver(rumps_module, title, subtitle, message, **kwargs) -> None:
        calls.append((rumps_module, title, subtitle, message, kwargs))

    rumps_module = types.SimpleNamespace(__name__="rumps")
    monkeypatch.setattr(notifications, "deliver_notification", fake_deliver)

    notifications.send_notification(
        rumps_module,
        "Title",
        "",
        "Body",
        logging.getLogger("test"),
        action_button="Record",
    )

    assert calls == [
        (
            rumps_module,
            "Title",
            "",
            "Body",
            {"action_button": "Record", "ignoreDnD": True},
        )
    ]

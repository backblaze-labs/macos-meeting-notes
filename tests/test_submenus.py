"""Tests for the setup tray's native Configuration submenu."""

from __future__ import annotations

from tray_fakes import FakeRumps

from meeting_memory.types.capabilities import Capability
from meeting_memory.ui import menu
from meeting_memory.ui.sidebar_view_model import ConfigurationActions
from meeting_memory.ui.submenus import configuration_submenu


def test_configuration_callbacks_accept_rumps_sender_and_preserve_native_actions() -> None:
    calls = []
    actions = ConfigurationActions(
        open_capability=lambda capability: calls.append(capability),
        import_legacy=lambda: calls.append("migration"),
        authorize_calendar=lambda: calls.append("authorization"),
        open_notes_prompt=lambda: calls.append("prompt"),
    )
    submenu = configuration_submenu(FakeRumps(), actions)
    items = {item.title: item for item in submenu.items if item is not None}

    for capability in Capability:
        items[f"{capability.label}..."].callback(object())
    items[menu.NOTES_PROMPT_LABEL].callback(object())
    items[menu.AUTHORIZE_CALENDAR_LABEL].callback(object())
    items[menu.IMPORT_LEGACY_LABEL].callback(object())

    assert calls == [*Capability, "prompt", "authorization", "migration"]


def test_setup_configuration_keeps_prompt_visible_but_safely_disabled() -> None:
    submenu = configuration_submenu(
        FakeRumps(),
        ConfigurationActions(lambda _capability: None, lambda: None, lambda: None, lambda: None),
        notes_prompt_available=False,
    )
    items = {item.title: item for item in submenu.items if item is not None}

    assert items[menu.NOTES_PROMPT_LABEL].callback is None
    assert "Recording Core setup" in items[menu.NOTES_PROMPT_LABEL].tooltip

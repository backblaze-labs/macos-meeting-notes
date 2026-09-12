"""Opt-in automatic Notes: off by default, confirmed before enabling."""

from __future__ import annotations

from pathlib import Path

from test_tray_notifications import FakeController
from tray_fakes import FakeRumps, submenu_titles

from meeting_memory.ui import menu
from meeting_memory.ui.notes_mode import (
    AUTOMATIC_NOTES_LABEL,
    CONFIRM_TITLE,
    MemoryDefaults,
    NotesMode,
)
from meeting_memory.ui.tray import RumpsTrayApp


def test_automatic_notes_are_off_by_default() -> None:
    mode = NotesMode(MemoryDefaults())

    assert mode.enabled() is False
    assert mode.label() == AUTOMATIC_NOTES_LABEL


def test_enabling_requires_accepting_the_tradeoff() -> None:
    mode = NotesMode(MemoryDefaults())
    rumps = FakeRumps()
    rumps.alert_response = 0

    assert mode.toggle(rumps) is False
    assert mode.enabled() is False
    assert rumps.alerts[0][0] == CONFIRM_TITLE
    assert "may still attribute" in rumps.alerts[0][1]

    rumps.alert_response = 1

    assert mode.toggle(rumps) is True
    assert mode.enabled() is True
    assert mode.label().startswith("\u2713 ")


def test_disabling_needs_no_confirmation() -> None:
    mode = NotesMode(MemoryDefaults())
    mode.set_enabled(True)
    rumps = FakeRumps()

    assert mode.toggle(rumps) is False
    assert mode.enabled() is False
    assert rumps.alerts == []


def test_configuration_menu_row_toggles_the_setting_and_refreshes(tmp_path: Path) -> None:
    fake_rumps = FakeRumps()
    app = RumpsTrayApp(FakeController(tmp_path), rumps_module=fake_rumps)

    assert app.automatic_notes() is False
    titles = submenu_titles(app, menu.CONFIGURATION_LABEL)
    assert AUTOMATIC_NOTES_LABEL in titles

    configuration = next(i for i in app.app.menu.items if i and i.title == menu.CONFIGURATION_LABEL)
    row = next(i for i in configuration.items if i and i.title == AUTOMATIC_NOTES_LABEL)
    row.callback(row)

    assert app.automatic_notes() is True
    assert f"\u2713 {AUTOMATIC_NOTES_LABEL}" in submenu_titles(app, menu.CONFIGURATION_LABEL)


def test_setting_persists_through_shared_defaults(tmp_path: Path) -> None:
    defaults = MemoryDefaults()
    NotesMode(defaults).set_enabled(True)

    app = RumpsTrayApp(FakeController(tmp_path), rumps_module=FakeRumps(), notes_defaults=defaults)

    assert app.automatic_notes() is True

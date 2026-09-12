"""Tests for the status-item menu that holds everything but the sidebar buttons."""

from __future__ import annotations

from dataclasses import replace

from sidebar_view_model_fixtures import RowView, SectionView, idle_view_model
from tray_fakes import FakeRumps

from meeting_memory.ui import menu
from meeting_memory.ui.status_menu import (
    HIDE_SIDEBAR_LABEL,
    SHOW_SIDEBAR_LABEL,
    rebuild_status_menu,
    sidebar_toggle_label,
)


def _titles(items) -> list[str | None]:
    return [item.title if item is not None else None for item in items]


def _submenu(app_menu, title):
    return next(item for item in app_menu.items if item is not None and item.title == title)


def test_menu_order_matches_the_spec_with_start_recording_first() -> None:
    app_menu = FakeRumps.App(name="Test").menu

    rebuild_status_menu(
        app_menu,
        FakeRumps(),
        idle_view_model(),
        sidebar_visible=False,
        on_toggle_recording=lambda: None,
        on_toggle_sidebar=lambda: None,
        on_quit=lambda: None,
    )

    assert _titles(app_menu.items) == [
        menu.APP_TITLE,
        None,
        "▶ Start Recording",
        None,
        SHOW_SIDEBAR_LABEL,
        None,
        menu.RECENT_HEADER,
        "2026-09-05 14:00 · Standup",
        None,
        menu.OPEN_MEETINGS_LABEL,
        None,
        menu.CONFIGURATION_LABEL,
        menu.DEBUGGING_LABEL,
        menu.QUIT_LABEL,
    ]
    assert _titles(_submenu(app_menu, menu.CONFIGURATION_LABEL).items) == [
        menu.AUDIO_MODE_HEADER,
        "✓ Full Meeting",
        "Silent System Only",
        None,
        "Notes Customization...",
    ]
    assert _titles(_submenu(app_menu, menu.DEBUGGING_LABEL).items) == [
        "Pending Meeting Tasks (0)",
        None,
        "Calendar: connected",
        None,
        "Check Setup & Dependencies",
    ]


def test_record_item_is_in_the_menu_but_screenshot_is_not() -> None:
    app_menu = FakeRumps.App(name="Test").menu
    calls: list[str] = []
    items = rebuild_status_menu(
        app_menu,
        FakeRumps(),
        idle_view_model(),
        sidebar_visible=False,
        on_toggle_recording=lambda: calls.append("record"),
        on_toggle_sidebar=lambda: None,
        on_quit=lambda: None,
    )
    items.recording.callback(items.recording)
    assert calls == ["record"]

    def all_titles(items):
        for item in items:
            if item is None:
                continue
            yield item.title
            yield from all_titles(item.items)

    titles = list(all_titles(app_menu.items))
    assert menu.SCREENSHOT_LABEL not in titles
    assert "▶ Start Recording" in titles


def test_actions_and_disabled_rows() -> None:
    app_menu = FakeRumps.App(name="Test").menu
    calls: list[str] = []
    view_model = replace(
        idle_view_model(),
        recent=SectionView(menu.RECENT_HEADER, rows=(), empty_label=menu.NO_MEETINGS_LABEL),
        recovered=SectionView(
            "Interrupted Recordings (1)",
            rows=(RowView("Recover x", action=lambda: calls.append("recover")),),
        ),
        open_meetings_folder=RowView("Open Meetings Folder", action=lambda: calls.append("open")),
    )

    toggle_item = rebuild_status_menu(
        app_menu,
        FakeRumps(),
        view_model,
        sidebar_visible=True,
        on_toggle_recording=lambda: None,
        on_toggle_sidebar=lambda: calls.append("toggle"),
        on_quit=lambda: calls.append("quit"),
        sidebar_rows=(
            RowView("Hide sidebar while recording", action=lambda: calls.append("pref")),
        ),
    ).sidebar_toggle

    assert toggle_item.title == HIDE_SIDEBAR_LABEL
    toggle_item.callback(toggle_item)
    empty = next(i for i in app_menu.items if i is not None and i.title == menu.NO_MEETINGS_LABEL)
    assert empty.callback is None
    _submenu(app_menu, menu.OPEN_MEETINGS_LABEL).callback(None)
    debugging = _submenu(app_menu, menu.DEBUGGING_LABEL)
    assert "Interrupted Recordings (1)" in _titles(debugging.items)
    _submenu(debugging, "Recover x").callback(None)
    _submenu(_submenu(app_menu, menu.CONFIGURATION_LABEL), "Hide sidebar while recording").callback(
        None
    )
    _submenu(app_menu, menu.QUIT_LABEL).callback(None)
    assert calls == ["toggle", "open", "recover", "pref", "quit"]
    readiness = _submenu(debugging, "Calendar: connected")
    assert readiness.callback is None and readiness.tooltip == "Google Calendar linked"


def test_sidebar_toggle_label() -> None:
    assert sidebar_toggle_label(True) == HIDE_SIDEBAR_LABEL
    assert sidebar_toggle_label(False) == SHOW_SIDEBAR_LABEL

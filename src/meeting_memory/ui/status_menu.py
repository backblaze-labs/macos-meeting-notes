"""The menu behind the menu bar icon: everything that is not a sidebar button.

The sidebar holds only record/stop, screenshot, and quit
(`docs/features/sidebar.md`). Recent meetings, the meetings folder,
Configuration, Debugging, and Quit live here, rebuilt from the same
`SidebarViewModel` snapshot after every state change. The menu is the rumps
`App.menu`; `ui/sidebar_toggle.py` detaches it from the status item at
install time and pops it up on a right-click.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from meeting_memory.ui import menu
from meeting_memory.ui.sidebar_view_model import RowView, SectionView, SidebarViewModel

SHOW_SIDEBAR_LABEL = "Show Sidebar"
HIDE_SIDEBAR_LABEL = "Hide Sidebar"
SIDEBAR_TOGGLE_TOOLTIP = "The sidebar holds Record, Screenshot, and Quit. Left-click the icon too."


def sidebar_toggle_label(visible: bool) -> str:
    return HIDE_SIDEBAR_LABEL if visible else SHOW_SIDEBAR_LABEL


def rebuild_status_menu(
    app_menu: Any,
    rumps: Any,
    view_model: SidebarViewModel,
    *,
    sidebar_visible: bool,
    on_toggle_sidebar: Callable[[], None],
    on_quit: Callable[..., None],
    sidebar_rows: Iterable[RowView] = (),
) -> Any:
    """Rebuild `app_menu` in place. Returns the Show/Hide Sidebar item so the
    caller can retitle it when the panel is toggled from the icon."""

    app_menu.clear()
    app_menu.add(rumps.MenuItem(menu.APP_TITLE, callback=None))
    app_menu.add(None)
    toggle_item = _item(
        rumps,
        RowView(
            sidebar_toggle_label(sidebar_visible),
            tooltip=SIDEBAR_TOGGLE_TOOLTIP,
            action=on_toggle_sidebar,
        ),
    )
    app_menu.add(toggle_item)
    app_menu.add(None)
    _add_section(app_menu, rumps, view_model.recent)
    app_menu.add(None)
    app_menu.add(_item(rumps, view_model.open_meetings_folder))
    app_menu.add(None)
    app_menu.add(_configuration_submenu(rumps, view_model, tuple(sidebar_rows)))
    app_menu.add(_debugging_submenu(rumps, view_model))
    app_menu.add(rumps.MenuItem(menu.QUIT_LABEL, lambda _sender: on_quit()))
    return toggle_item


def _configuration_submenu(
    rumps: Any, view_model: SidebarViewModel, sidebar_rows: tuple[RowView, ...]
) -> Any:
    submenu = rumps.MenuItem(menu.CONFIGURATION_LABEL)
    submenu.add(rumps.MenuItem(menu.AUDIO_MODE_HEADER, callback=None))
    for row in view_model.audio_modes:
        submenu.add(_item(rumps, row))
    submenu.add(None)
    for row in (*view_model.configuration, *sidebar_rows):
        submenu.add(_item(rumps, row))
    return submenu


def _debugging_submenu(rumps: Any, view_model: SidebarViewModel) -> Any:
    submenu = rumps.MenuItem(menu.DEBUGGING_LABEL)
    _add_section(submenu, rumps, view_model.processing)
    submenu.add(None)
    for row in view_model.readiness:
        submenu.add(_item(rumps, row))
    if view_model.readiness:
        submenu.add(None)
    if view_model.recovered.rows:
        _add_section(submenu, rumps, view_model.recovered)
        submenu.add(None)
    for row in view_model.diagnostics:
        submenu.add(_item(rumps, row))
    return submenu


def _add_section(target: Any, rumps: Any, section: SectionView) -> None:
    target.add(rumps.MenuItem(section.title, callback=None))
    for row in section.rows:
        target.add(_item(rumps, row))
    if not section.rows and section.empty_label is not None:
        target.add(rumps.MenuItem(section.empty_label, callback=None))


def _item(rumps: Any, row: RowView) -> Any:
    action = row.action if row.enabled else None
    callback = (lambda _sender, action=action: action()) if action is not None else None
    item = rumps.MenuItem(row.label, callback)
    if row.tooltip:
        _set_tooltip(item, row.tooltip)
    return item


def _set_tooltip(item: Any, tooltip: str) -> None:
    item.tooltip = tooltip
    native_item = getattr(item, "_menuitem", None)
    set_tooltip = getattr(native_item, "setToolTip_", None)
    if callable(set_tooltip):
        set_tooltip(tooltip)

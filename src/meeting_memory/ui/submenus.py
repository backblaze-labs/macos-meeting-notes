"""Native configuration submenu for the setup tray.

The runtime tray no longer builds menus (docs/features/sidebar.md); only
`ui/setup_tray.py` still composes one, and this is what it needs.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from meeting_memory.types.capabilities import Capability
from meeting_memory.ui import menu
from meeting_memory.ui.sidebar_view_model import ConfigurationActions

__all__ = [
    "ConfigurationActions",
    "configuration_submenu",
    "configuration_surface_actions",
]


def configuration_surface_actions(surface: Any) -> ConfigurationActions:
    return ConfigurationActions(
        open_capability=surface.open_capability,
        import_legacy=surface.preview_migration,
        authorize_calendar=surface.authorize_calendar,
        open_notes_prompt=surface.edit_notes_prompt,
    )


def configuration_submenu(
    rumps: Any,
    actions: ConfigurationActions,
    *,
    notes_prompt_available: bool = True,
) -> Any:
    submenu = rumps.MenuItem(menu.CONFIGURATION_LABEL)
    for capability in Capability:
        submenu.add(
            rumps.MenuItem(
                f"{capability.label}...",
                lambda _sender, item=capability: actions.open_capability(item),
            )
        )
    submenu.add(None)
    submenu.add(
        _menu_item(
            rumps,
            menu.NOTES_PROMPT_LABEL,
            (lambda _sender: actions.open_notes_prompt()) if notes_prompt_available else None,
            tooltip=(
                "Customize AI instructions and the local report layout used by Notes."
                if notes_prompt_available
                else "Available after Recording Core setup is complete and the app restarts."
            ),
        )
    )
    submenu.add(
        rumps.MenuItem(
            menu.AUTHORIZE_CALENDAR_LABEL,
            lambda _sender: actions.authorize_calendar(),
        )
    )
    submenu.add(rumps.MenuItem(menu.IMPORT_LEGACY_LABEL, lambda _sender: actions.import_legacy()))
    return submenu


def _menu_item(
    rumps: Any,
    title: str,
    callback: Callable[..., None] | None = None,
    *,
    tooltip: str,
) -> Any:
    item = rumps.MenuItem(title, callback)
    item.tooltip = tooltip
    native_item = getattr(item, "_menuitem", None)
    set_tooltip = getattr(native_item, "setToolTip_", None)
    if callable(set_tooltip):
        set_tooltip(tooltip)
    return item

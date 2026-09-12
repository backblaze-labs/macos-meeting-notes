"""Wires the floating panel and its compact content into RumpsTrayApp.

Split out of `ui/tray.py` to keep it under its line budget. The panel shows
three icon buttons (`ui/sidebar_compact.py`); every other control is in the
ordinary status-item menu (`ui/status_menu.py`). Nothing here touches rumps
internals: the menu bar icon keeps its normal click behavior.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

from meeting_memory.ui.sidebar_compact import build_compact
from meeting_memory.ui.sidebar_geometry import Orientation
from meeting_memory.ui.sidebar_panel import SidebarPanel
from meeting_memory.ui.sidebar_prefs import (
    hide_while_recording,
    hide_while_recording_label,
    set_hide_while_recording,
)
from meeting_memory.ui.sidebar_view_model import RowView, recording_view_for

HIDE_WHILE_RECORDING_TOOLTIP = (
    "When on, the sidebar does not appear by itself when a recording starts."
)


class SidebarWiring:
    """None-safe home for the sidebar panel and its content.

    The panel exists only in the real app: a non-None `rumps_module` means
    a test fake, and tests that want a panel inject a `panel_factory`
    explicitly. Every method is a no-op without one.
    """

    def __init__(
        self,
        rumps_module: Any,
        *,
        on_toggle_recording: Callable[[], None] = lambda: None,
        on_screenshot: Callable[[], None] = lambda: None,
        on_quit: Callable[[], None] = lambda: None,
        panel_factory: Any = None,
    ) -> None:
        self._on_toggle_recording = on_toggle_recording
        self._on_screenshot = on_screenshot
        self._on_quit = on_quit
        if panel_factory is None and rumps_module is None:
            panel_factory = SidebarPanel
        self.panel = (
            panel_factory(on_anchor_changed=self._handle_anchor_changed)
            if panel_factory is not None
            else None
        )
        self._recording: Any = None
        self._built_recording = False
        self._view_model: Any = None
        self._last_orientation: Orientation | None = (
            self.panel.orientation if self.panel is not None else None
        )

    @property
    def is_visible(self) -> bool:
        return self.panel is not None and self.panel.is_visible

    def rebuild(self, view_model: Any) -> None:
        """Rebuild the panel's content from `view_model` — the same immutable
        snapshot that builds the status-item menu. Also re-invoked by
        `_handle_anchor_changed` on an orientation swap and by `tick` when the
        recording state changes under it, both against the last snapshot."""

        if self.panel is None:
            return
        self._view_model = view_model
        views = build_compact(
            self.panel.appkit,
            view_model,
            orientation=self.panel.orientation,
            on_toggle_recording=self._on_toggle_recording,
            on_screenshot=self._on_screenshot,
            on_quit=self._on_quit,
        )
        self.panel.set_content_view(views.root)
        self._recording = views.recording
        self._built_recording = view_model.recording.is_recording
        self._last_orientation = self.panel.orientation

    def preference_rows(self, on_change: Callable[[], None]) -> tuple[RowView, ...]:
        """The panel's own settings, for the status menu's Configuration
        submenu. They are sidebar chrome (NSUserDefaults, `sidebar_prefs.py`),
        not app state, so `build_view_model` knows nothing about them."""

        if self.panel is None:
            return ()
        appkit = self.panel.appkit

        def toggle() -> None:
            set_hide_while_recording(appkit, not hide_while_recording(appkit))
            on_change()

        return (
            RowView(
                label=hide_while_recording_label(appkit),
                tooltip=HIDE_WHILE_RECORDING_TOOLTIP,
                action=toggle,
            ),
        )

    def _handle_anchor_changed(self, _anchor: Any) -> None:
        # Orientation, not the anchor itself, decides whether content needs
        # rebuilding: LEFT -> RIGHT stays vertical and needs nothing here —
        # `SidebarPanel` already repositions itself.
        if self._view_model is None or self.panel.orientation is self._last_orientation:
            return
        self.rebuild(self._view_model)

    def toggle_panel(self) -> None:
        """Show/Hide Sidebar from the menu.

        Visibility is the user's decision from here on: nothing in the wiring
        shows or hides the panel again until the next recording starts.
        """

        if self.panel is None:
            return
        self.panel.toggle()

    def tick(self, controller: Any) -> None:
        """The 1 Hz tick: update the record button in place and rebuild when
        the recording state flipped (the timer slot changes the panel size).
        Visibility is never changed here."""

        if self._recording is None:
            return
        view = recording_view_for(controller)
        if view.is_recording != self._built_recording and self._view_model is not None:
            self.rebuild(replace(self._view_model, recording=view))
        else:
            self._recording.update(view)

    def reveal(self) -> None:
        """Auto-show when a recording starts (docs/features/sidebar.md).

        The controller queues one `SidebarRevealRequested` per recording start,
        from every start path, so this is the only automatic show. With "Hide
        sidebar while recording" on it does nothing, and it never hides. A
        panel the user closed stays closed until the next recording starts.
        """

        if self.panel is None or hide_while_recording(self.panel.appkit):
            return
        self.panel.show()

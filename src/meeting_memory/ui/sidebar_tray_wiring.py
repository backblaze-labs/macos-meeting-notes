"""Wires SidebarToggle and the compact panel content into RumpsTrayApp.

Split out of `ui/tray.py` to keep it under its line budget. The panel shows
three icon buttons (`ui/sidebar_compact.py`); every other control is in the
status-item menu (`ui/status_menu.py`).
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
from meeting_memory.ui.sidebar_toggle import SidebarToggle
from meeting_memory.ui.sidebar_view_model import RowView, recording_view_for

# A failed toggle install is retried on later ticks, but not forever: each
# failure logs a traceback, and a permanent AppKit failure would otherwise
# log once a second for the life of the process.
MAX_INSTALL_ATTEMPTS = 3
HIDE_WHILE_RECORDING_TOOLTIP = (
    "When on, starting a recording hides the sidebar instead of showing it."
)


class SidebarWiring:
    """None-safe home for the sidebar panel + toggle + content.

    The panel exists only in the real app: a non-None `rumps_module` means
    a test fake, and tests that want a panel inject a `panel_factory`
    explicitly. Every method is a no-op without one.

    `install_once()` installs the status-item toggle once. Call it from the
    first timer tick: `nsstatusitem` doesn't exist until `rumps.App.run()`
    has started (it is attached inside `applicationDidFinishLaunching_`), so
    installing from `__init__` or `run()` itself is too early.
    """

    def __init__(
        self,
        rumps_module: Any,
        *,
        on_toggle_recording: Callable[[], None] = lambda: None,
        on_screenshot: Callable[[], None] = lambda: None,
        on_quit: Callable[[], None] = lambda: None,
        panel_factory: Any = None,
        click_appkit: Any = None,
    ) -> None:
        self._on_toggle_recording = on_toggle_recording
        self._on_screenshot = on_screenshot
        self._on_quit = on_quit
        self._click_appkit = click_appkit  # tests inject a fake; None -> real AppKit
        self._install_attempts = 0
        # "Hide sidebar while recording": an explicit icon click during a
        # recording is a deliberate peek, so the per-tick hide stands down
        # until the recording ends.
        self._peeking = False
        if panel_factory is None and rumps_module is None:
            panel_factory = SidebarPanel
        self.panel = (
            panel_factory(on_anchor_changed=self._handle_anchor_changed)
            if panel_factory is not None
            else None
        )
        self.toggle: SidebarToggle | None = None
        self._recording: Any = None
        self._built_recording = False
        self._view_model: Any = None
        self._last_orientation: Orientation | None = (
            self.panel.orientation if self.panel is not None else None
        )

    @property
    def is_visible(self) -> bool:
        return self.panel is not None and self.panel.is_visible

    def install_once(self, app: Any, rumps_module: Any) -> None:
        if self.panel is None or self.toggle is not None:
            return
        self._install_attempts += 1
        toggle = SidebarToggle(
            app,
            _PanelToggleProxy(self),
            on_quit=rumps_module.quit_application,
            appkit=self._click_appkit,
        )
        if toggle.install() or self._install_attempts >= MAX_INSTALL_ATTEMPTS:
            self.toggle = toggle  # installed, or given up: either way stop retrying

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
        """The status item's left-click (and the menu's Show/Hide Sidebar),
        routed here so a deliberate peek during a recording is remembered."""

        if self.panel is None:
            return
        self._peeking = self.panel.toggle()

    def tick(self, controller: Any) -> None:
        """The 1 Hz tick: update the record button in place, rebuild when the
        recording state flipped (the timer slot changes the panel size), and
        keep the panel hidden while recording if the user asked for that."""

        if self._recording is None:
            return
        view = recording_view_for(controller)
        if view.is_recording != self._built_recording and self._view_model is not None:
            self.rebuild(replace(self._view_model, recording=view))
        else:
            self._recording.update(view)
        if self.toggle is not None:
            self.toggle.set_recording_indicator(view.is_recording)
        self._enforce_hide_while_recording(view.is_recording)

    def _enforce_hide_while_recording(self, is_recording: bool) -> None:
        # Whatever showed the panel mid-recording — a rebuild, a reveal, an
        # orientation swap — it goes back to hidden, in either orientation.
        # Only the user's own icon click (`toggle`) is allowed to override,
        # and that override ends with the recording.
        if not is_recording:
            self._peeking = False
            return
        if self._peeking or not hide_while_recording(self.panel.appkit):
            return
        if self.panel.is_visible:
            self.panel.hide()

    def reveal(self) -> None:
        """Auto-show on record start (docs/features/sidebar.md) — or, when the
        user turned on "Hide sidebar while recording", the opposite.

        A no-op when the sidebar isn't present. Either way it is a one-shot
        nudge, not a lock: the user can toggle the panel right after.
        """

        if self.panel is None:
            return
        if hide_while_recording(self.panel.appkit):
            self._peeking = False
            self.panel.hide()
        else:
            self.panel.show()


class _PanelToggleProxy:
    """`SidebarToggle`'s `TogglePanel`: forwards the icon click to the wiring
    (`SidebarWiring.toggle` is the installed `SidebarToggle`, so the wiring
    itself can't play that role)."""

    def __init__(self, wiring: SidebarWiring) -> None:
        self._wiring = wiring

    def toggle(self) -> None:
        self._wiring.toggle_panel()

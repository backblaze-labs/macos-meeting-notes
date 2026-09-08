"""Wires SidebarToggle and the panel's vertical/horizontal content into
RumpsTrayApp.

Split out of `ui/tray.py` to keep it under its line budget — see
docs/features/sidebar/completed/03-status-item-toggle.md (toggle),
docs/features/sidebar/completed/05-vertical-content.md (vertical content), and
docs/features/sidebar/completed/06-horizontal-layout.md (horizontal content
and orientation switching).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

from meeting_memory.ui.sidebar_geometry import Orientation
from meeting_memory.ui.sidebar_horizontal import build_horizontal, show_overflow_popover
from meeting_memory.ui.sidebar_panel import SidebarPanel
from meeting_memory.ui.sidebar_prefs import (
    hide_while_recording,
    hide_while_recording_label,
    set_hide_while_recording,
)
from meeting_memory.ui.sidebar_sections import SectionState
from meeting_memory.ui.sidebar_toggle import SidebarToggle
from meeting_memory.ui.sidebar_vertical import build_vertical
from meeting_memory.ui.sidebar_view_model import RowView, recording_view_for

# A failed toggle install is retried on later ticks, but not forever: each
# failure logs a traceback, and a permanent AppKit failure would otherwise
# log once a second for the life of the process.
MAX_INSTALL_ATTEMPTS = 3


class SidebarWiring:
    """None-safe home for the sidebar panel + toggle + content.

    The panel exists only in the real app: a non-None `rumps_module` means
    a test fake, and tests that want a panel inject a `panel_factory`
    explicitly. Every method is a no-op without one.

    `install_once()` installs the status-item toggle once. Call it from the
    first timer tick:
    `nsstatusitem` doesn't exist until `rumps.App.run()` has started (it is
    attached inside `applicationDidFinishLaunching_`), so installing from
    `__init__` or `run()` itself is too early.

    `on_toggle_recording` and `on_quit` are fixed for the app's lifetime, so
    they're bound once here rather than threaded through every `rebuild()`.
    """

    def __init__(
        self,
        rumps_module: Any,
        *,
        on_toggle_recording: Callable[[], None] = lambda: None,
        on_quit: Callable[[], None] = lambda: None,
        panel_factory: Any = None,
        click_appkit: Any = None,
    ) -> None:
        self._on_toggle_recording = on_toggle_recording
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
        self._section_state: SectionState | None = None
        self._recording_row: Any = None
        self._view_model: Any = None
        self._overflow_button: Any = None
        self._popover: Any = None
        self._popover_recording_row: Any = None
        self._last_orientation: Orientation | None = (
            self.panel.orientation if self.panel is not None else None
        )

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
        """Tear down and rebuild the panel's content from `view_model`.

        Called from `rebuild_menu()` — the same immutable snapshot that
        builds the dropdown menu also builds the panel, per plan 04. A
        section toggle re-invokes this (via `on_rebuild`) against the same
        `view_model`, since toggling a section doesn't change app state.
        Also re-invoked by `_handle_anchor_changed` on an orientation swap,
        against the last `view_model` seen — a drag release fires no new
        app state, so there is nothing fresher to render.
        """

        if self.panel is None:
            return
        # Keep the *raw* snapshot: every re-entry (section toggle, anchor
        # change, popover) augments it again, so storing the augmented copy
        # would append the preference row once more per rebuild.
        self._view_model = view_model
        rendered = self._with_sidebar_preferences(view_model)
        if self._section_state is None:
            self._section_state = SectionState(self.panel.appkit)
        # App state changed under an open popover: drop it rather than let
        # it show a stale recording row whose click toggles live state.
        self._close_popover()

        if self.panel.orientation is Orientation.HORIZONTAL:
            views = build_horizontal(
                self.panel.appkit,
                rendered,
                on_toggle_recording=self._on_toggle_recording,
                on_overflow=self._show_overflow,
            )
            self._overflow_button = views.overflow_button
            content, recording_row = views.root, views.recording
        else:
            content, recording_row = build_vertical(
                self.panel.appkit,
                rendered,
                self._section_state,
                on_toggle_recording=self._on_toggle_recording,
                on_quit=self._on_quit,
                on_rebuild=lambda: self.rebuild(view_model),
                max_height=self.panel.max_content_height(),
            )
        self.panel.set_content_view(content)
        self._recording_row = recording_row
        self._last_orientation = self.panel.orientation

    def _with_sidebar_preferences(self, view_model: Any) -> Any:
        """Append the panel's own settings to the Configuration section.

        They are sidebar chrome (NSUserDefaults, see `sidebar_prefs.py`),
        not app state, so `build_view_model` in `ui/tray.py` knows nothing
        about them — the row is added here, where the panel is.
        """

        appkit = self.panel.appkit

        def toggle() -> None:
            set_hide_while_recording(appkit, not hide_while_recording(appkit))
            self.rebuild(view_model)

        row = RowView(
            label=hide_while_recording_label(appkit),
            tooltip="When on, starting a recording hides the sidebar instead of showing it.",
            action=toggle,
        )
        return replace(view_model, configuration=(*view_model.configuration, row))

    def _handle_anchor_changed(self, _anchor: Any) -> None:
        # Orientation, not the anchor itself, decides whether content needs
        # rebuilding: LEFT -> RIGHT stays vertical and needs nothing here —
        # `SidebarPanel` already repositions itself. Not a hot path either
        # way: this only runs once per drag release (gotcha "swap cost").
        if self._view_model is None or self.panel.orientation is self._last_orientation:
            return
        self.rebuild(self._view_model)

    def _show_overflow(self) -> None:
        """`⋯` was clicked: pop plan 05's vertical stack up as a popover,
        anchored to the button, opening away from the screen edge (gotcha 6)."""

        self._close_popover()  # a section toggle inside it re-opens fresh, not stacked

        content, self._popover_recording_row = build_vertical(
            self.panel.appkit,
            self._with_sidebar_preferences(self._view_model),
            self._section_state,
            on_toggle_recording=self._on_toggle_recording,
            on_quit=self._on_quit,
            on_rebuild=lambda: self._show_overflow(),
            max_height=self.panel.max_content_height(),
        )
        self._popover = show_overflow_popover(
            self.panel.appkit,
            overflow_button=self._overflow_button,
            anchor=self.panel.anchor,
            content_view=content,
            panel=self.panel,
        )

    def _close_popover(self) -> None:
        if self._popover is not None:
            self._popover.close()
        self._popover = None
        self._popover_recording_row = None

    def toggle_panel(self) -> None:
        """The status item's left-click, routed here (not straight to the
        panel) so a deliberate peek during a recording is remembered."""

        self._peeking = self.panel.toggle()

    def tick(self, controller: Any) -> None:
        """The 1 Hz tick: update the recording row(s) in place, no rebuild,
        and keep the panel hidden while recording if the user asked for that."""

        if self._recording_row is None:
            return
        view = recording_view_for(controller)
        self._recording_row.update(view)
        if self._popover_recording_row is not None:
            self._popover_recording_row.update(view)
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
            self._close_popover()
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
            self._close_popover()
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

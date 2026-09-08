"""Tests for SidebarWiring's orientation-switch and overflow-popover
behavior — see docs/features/sidebar/completed/06-horizontal-layout.md.

Split from test_sidebar_tray_wiring.py (plans 03/05's file) since building
horizontal content and its popover needs a richer fake AppKit (NSPopUpButton,
NSObject, NSViewController, NSPopover) than the panel-focused fakes there
provide — reusing plan 06's own `sidebar_horizontal_fakes.py` instead of
extending a shared file others are also using.
"""

from __future__ import annotations

import pytest
from appkit_fakes import reset_fake_appkit_state
from sidebar_horizontal_fakes import FakeNSPopover, HorizontalFakeAppKit
from sidebar_view_model_fixtures import idle_view_model

from meeting_memory.ui.sidebar_geometry import Orientation, SnapAnchor
from meeting_memory.ui.sidebar_tray_wiring import SidebarWiring


@pytest.fixture(autouse=True)
def _reset_appkit_state():
    reset_fake_appkit_state()
    yield
    reset_fake_appkit_state()


class FakePanel:
    def __init__(self, appkit=None, on_anchor_changed=None):
        self.appkit = appkit if appkit is not None else HorizontalFakeAppKit()
        self.on_anchor_changed = on_anchor_changed
        self.orientation = Orientation.VERTICAL
        self.anchor = SnapAnchor.LEFT
        self.content_view = None
        self.show_calls = 0
        self.is_visible = False

    def set_content_view(self, view) -> None:
        self.content_view = view

    def max_content_height(self) -> float | None:
        return None

    def show(self) -> None:
        self.show_calls += 1
        self.is_visible = True

    def hide(self) -> None:
        self.is_visible = False

    def drag_to(self, anchor: SnapAnchor, orientation: Orientation) -> None:
        self.anchor = anchor
        self.orientation = orientation
        if self.on_anchor_changed is not None:
            self.on_anchor_changed(anchor)


def _wiring() -> SidebarWiring:
    return SidebarWiring(None, panel_factory=FakePanel)


def test_rebuild_builds_vertical_content_by_default() -> None:
    wiring = _wiring()
    wiring.rebuild(idle_view_model())
    # The vertical stack's frame is 240 wide; the horizontal bar's is 620.
    assert wiring.panel.content_view.frame().size.width == 240.0


def test_anchor_change_to_horizontal_rebuilds_as_the_compact_bar() -> None:
    wiring = _wiring()
    wiring.rebuild(idle_view_model())

    wiring.panel.drag_to(SnapAnchor.TOP, Orientation.HORIZONTAL)

    assert wiring.panel.content_view.frame().size.width == 620.0


def test_anchor_change_within_the_same_orientation_does_not_rebuild() -> None:
    wiring = _wiring()
    wiring.rebuild(idle_view_model())
    content_before = wiring.panel.content_view

    wiring.panel.drag_to(SnapAnchor.RIGHT, Orientation.VERTICAL)

    assert wiring.panel.content_view is content_before


def test_anchor_change_before_any_rebuild_is_a_noop() -> None:
    wiring = _wiring()
    wiring.panel.drag_to(SnapAnchor.TOP, Orientation.HORIZONTAL)  # should not raise
    assert wiring.panel.content_view is None


def test_overflow_click_shows_a_popover_hosting_the_vertical_stack() -> None:
    wiring = _wiring()
    wiring.rebuild(idle_view_model())
    wiring.panel.drag_to(SnapAnchor.BOTTOM, Orientation.HORIZONTAL)
    overflow_button = wiring._overflow_button
    FakeNSPopover.shown = []

    overflow_button.mouseUp_(None)

    assert wiring.panel.show_calls == 1
    popover = wiring._popover
    assert popover.content_view_controller.view.frame().size.width == 240.0
    assert FakeNSPopover.shown[-1][2] == wiring.panel.appkit.NSMaxYEdge  # BOTTOM -> upward


def test_reopening_the_overflow_popover_closes_the_previous_one() -> None:
    wiring = _wiring()
    wiring.rebuild(idle_view_model())
    wiring.panel.drag_to(SnapAnchor.TOP, Orientation.HORIZONTAL)
    overflow_button = wiring._overflow_button

    overflow_button.mouseUp_(None)
    first_popover = wiring._popover
    overflow_button.mouseUp_(None)

    assert first_popover.closed is True
    assert wiring._popover is not first_popover


def test_a_rebuild_closes_an_open_popover_and_the_tick_reaches_its_recording_row() -> None:
    # Regression: an open popover kept a frozen snapshot — its "Start"
    # row could stop a recording that had started underneath it.
    wiring = _wiring()
    wiring.rebuild(idle_view_model())
    wiring.panel.drag_to(SnapAnchor.TOP, Orientation.HORIZONTAL)
    wiring._overflow_button.mouseUp_(None)
    popover = wiring._popover
    assert wiring._popover_recording_row is not None

    wiring.tick(_RecordingController())
    popover_label = popover.content_view_controller.view.subviews
    assert any("0:07" in _texts(v) for v in popover_label)

    wiring.rebuild(idle_view_model())

    assert popover.closed is True
    assert wiring._popover is None


class _RecordingController:
    class recorder:  # noqa: N801 — shaped like TrayController.recorder
        is_recording = True
        recording_warning = None

    def recording_duration_seconds(self) -> int:
        return 7


def _texts(view) -> str:
    return " ".join(
        getattr(sub, "text", "") or "" for sub in [view, *getattr(view, "subviews", [])]
    )

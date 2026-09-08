"""Fake-AppKit tests for the drag-handle view (plan 02, sidebar_panel.py)."""

from __future__ import annotations

import pytest
from appkit_fakes import FakeAppKit, fake_make_point, fake_make_rect, reset_fake_appkit_state

from meeting_memory.ui.sidebar_drag import make_drag_handle_view


class _FakeWindow:
    def __init__(self, frame):
        self._frame = frame
        self.origin_calls = []

    def frame(self):
        return self._frame

    def setFrameOrigin_(self, point) -> None:
        self.origin_calls.append(point)
        size = self._frame.size
        self._frame = fake_make_rect(point.x, point.y, size.width, size.height)


@pytest.fixture(autouse=True)
def _reset_appkit_state():
    reset_fake_appkit_state()
    yield
    reset_fake_appkit_state()


def test_two_drag_handles_reuse_one_view_class_and_dispatch_independently():
    # Same regression concern as sidebar_widgets.py's clickable rows: pyobjc
    # forbids redefining a same-named Objective-C class, so a second
    # SidebarPanel (or a test constructing two) must not create a fresh
    # `class DragHandleView(...)` — see `_drag_handle_view_class`.
    appkit = FakeAppKit()
    calls_a = []
    calls_b = []

    view_a = make_drag_handle_view(appkit, on_drag_end=lambda: calls_a.append(1))
    view_b = make_drag_handle_view(appkit, on_drag_end=lambda: calls_b.append(1))

    assert type(view_a) is type(view_b)
    view_a.mouseUp_(None)
    view_b.mouseUp_(None)
    assert calls_a == [1]
    assert calls_b == [1]


def test_vibrancy_is_configured():
    appkit = FakeAppKit()

    view = make_drag_handle_view(appkit, on_drag_end=lambda: None)

    assert view.material == appkit.NSVisualEffectMaterialHUDWindow
    assert view.blending_mode == appkit.NSVisualEffectBlendingModeBehindWindow
    assert view.state == appkit.NSVisualEffectStateActive


def test_drag_moves_window_by_screen_space_delta():
    appkit = FakeAppKit()
    view = make_drag_handle_view(appkit, on_drag_end=lambda: None)
    window = _FakeWindow(fake_make_rect(100.0, 100.0, 240.0, 460.0))
    view._window = window

    appkit.NSEvent.location = fake_make_point(150.0, 150.0)
    view.mouseDown_(None)
    appkit.NSEvent.location = fake_make_point(170.0, 130.0)
    view.mouseDragged_(None)

    assert window.origin_calls[-1].x == 120.0
    assert window.origin_calls[-1].y == 80.0


def test_mouse_up_clears_drag_state_and_fires_callback_once():
    appkit = FakeAppKit()
    calls = []
    view = make_drag_handle_view(appkit, on_drag_end=lambda: calls.append(1))
    view._window = _FakeWindow(fake_make_rect(0.0, 0.0, 240.0, 460.0))

    view.mouseDown_(None)
    view.mouseUp_(None)

    assert calls == [1]
    assert view._mm_drag_start is None


def test_drag_indicator_is_a_pass_through_grabber():
    # The `⠿` grabber sits exactly where a user will press to drag; if the
    # label itself answered hit-tests it would swallow that mouse-down and
    # the drag view underneath would never start tracking (manual pass of
    # plan 06 — `hitTest_` returned NSTextField at the strip's center).
    from meeting_memory.ui.sidebar_drag import (
        make_drag_indicator,
        make_drag_strip,
        position_drag_indicator,
    )

    appkit = FakeAppKit()
    indicator = make_drag_indicator(appkit)
    strip = make_drag_strip(appkit)
    assert indicator.stringValue() == "⠿"
    assert indicator.hitTest_(fake_make_point(120.0, 307.0)) is None
    assert strip.hitTest_(fake_make_point(5.0, 307.0)) is None
    assert type(indicator) is type(make_drag_indicator(appkit))  # one ObjC subclass

    position_drag_indicator(appkit, indicator, strip, 240.0, 314.0, 14.0)
    frame = indicator.frame()
    assert (frame.origin.x, frame.origin.y) == (90.0, 301.0)
    assert (frame.size.width, frame.size.height) == (60.0, 12.0)
    assert (strip.frame().origin.y, strip.frame().size.width) == (300.0, 240.0)

    position_drag_indicator(appkit, indicator, strip, 620.0, 56.0, 0.0)  # horizontal: parked
    assert indicator.frame().size.width == 0.0
    assert strip.frame().size.width == 0.0

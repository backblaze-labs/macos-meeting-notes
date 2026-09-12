"""Fake-AppKit tests for the sidebar's click-tracking view primitive."""

from __future__ import annotations

import pytest
from appkit_fakes import FakeAppKit, fake_make_rect, reset_fake_appkit_state
from appkit_widget_fakes import FakeNSView

from meeting_memory.ui.sidebar_widgets import clickable_view


@pytest.fixture(autouse=True)
def _reset_appkit_state():
    reset_fake_appkit_state()
    yield
    reset_fake_appkit_state()


def test_clickable_view_invokes_its_callback_on_mouse_up():
    appkit = FakeAppKit()
    calls = []

    view = clickable_view(appkit, lambda: calls.append(1), fake_make_rect(0.0, 0.0, 32.0, 32.0))

    view.mouseUp_(None)
    view.mouseUp_(None)
    assert calls == [1, 1]
    assert view.frame().size.width == 32.0


def test_disabled_view_is_a_plain_view_with_no_click_target():
    appkit = FakeAppKit()

    view = clickable_view(appkit, None, fake_make_rect(0.0, 0.0, 32.0, 32.0))

    assert type(view) is FakeNSView
    assert not hasattr(view, "mouseUp_")


def test_clickable_views_reuse_one_view_class_per_appkit_binding():
    # pyobjc registers the Objective-C class by name; redefining it per
    # button would raise on the second one. Two namespaces sharing one
    # `NSView` base share one subclass, and callbacks stay per-instance.
    first = clickable_view(FakeAppKit(), lambda: None, fake_make_rect(0.0, 0.0, 1.0, 1.0))
    second = clickable_view(FakeAppKit(), lambda: None, fake_make_rect(0.0, 0.0, 1.0, 1.0))

    assert type(first) is type(second)
    assert first._mm_on_click is not second._mm_on_click

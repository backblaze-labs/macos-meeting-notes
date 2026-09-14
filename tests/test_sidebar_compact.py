"""Fake-AppKit tests for the compact icon-only sidebar content."""

from __future__ import annotations

import pytest
from appkit_fakes import FakeAppKit, reset_fake_appkit_state
from appkit_widget_fakes import FakeNSImage, FakeNSImageView, FakeNSTextField
from sidebar_view_model_fixtures import RecordingView, idle_view_model

from meeting_memory.ui.sidebar_compact import (
    BUTTON,
    GAP,
    GRIP_WIDTH,
    HIDE_SYMBOL,
    INSET,
    QUIT_SYMBOL,
    RECORD_ACTIVE_SYMBOL,
    RECORD_IDLE_SYMBOL,
    SCREENSHOT_SYMBOL,
    TIMER_HEIGHT,
    TIMER_WIDTH,
    build_compact,
    compact_size,
    record_tooltip,
    timer_text,
)
from meeting_memory.ui.sidebar_geometry import Orientation


@pytest.fixture(autouse=True)
def _reset_appkit_state():
    reset_fake_appkit_state()
    yield
    reset_fake_appkit_state()


def _build(view_model=None, *, orientation=Orientation.VERTICAL, **callbacks):
    view_model = view_model or idle_view_model()
    callbacks.setdefault("on_toggle_recording", lambda: None)
    callbacks.setdefault("on_screenshot", lambda: None)
    callbacks.setdefault("on_hide_sidebar", lambda: None)
    callbacks.setdefault("on_quit", lambda: None)
    return build_compact(FakeAppKit(), view_model, orientation=orientation, **callbacks)


def _buttons(root):
    return [sub for sub in root.subviews if hasattr(sub, "_mm_image_view")]


def _symbol(button) -> str:
    return button._mm_image_view.image.name


def _recording(is_recording: bool, duration: int = 0, warning: bool = False) -> RecordingView:
    return RecordingView(
        is_recording=is_recording, duration_seconds=duration, audio_warning=warning, label="x"
    )


def test_vertical_layout_stacks_record_screenshot_hide_quit_top_to_bottom():
    views = _build()

    buttons = _buttons(views.root)
    assert [_symbol(b) for b in buttons] == [
        RECORD_IDLE_SYMBOL,
        SCREENSHOT_SYMBOL,
        HIDE_SYMBOL,
        QUIT_SYMBOL,
    ]
    ys = [b.frame().origin.y for b in buttons]
    assert ys == sorted(ys, reverse=True)  # AppKit y grows upward: record is on top
    assert all(b.frame().origin.x == INSET for b in buttons)
    assert (views.width, views.height) == compact_size(Orientation.VERTICAL, is_recording=False)
    assert views.height == 2 * INSET + 4 * BUTTON + 3 * GAP


def test_horizontal_layout_has_a_grip_then_buttons_left_to_right():
    views = _build(orientation=Orientation.HORIZONTAL)

    buttons = _buttons(views.root)
    xs = [b.frame().origin.x for b in buttons]
    assert xs == sorted(xs)
    assert xs[0] == GRIP_WIDTH + INSET
    grip = views.root.subviews[0]
    assert grip.frame().size.width == GRIP_WIDTH
    assert grip.subviews[0].text == "⠿"
    assert views.height == BUTTON + 2 * INSET


def test_buttons_are_icons_with_tooltips_not_words():
    views = _build()

    for button in _buttons(views.root):
        image_view = button._mm_image_view
        assert isinstance(image_view, FakeNSImageView)
        assert image_view.image.point_size == 18.0
        assert not isinstance(button.subviews[0], FakeNSTextField)
        assert button.tooltip
    tooltips = [b.tooltip for b in _buttons(views.root)]
    assert tooltips == [
        "Start recording",
        "Take screenshot (⌥⇧S)",
        "Hide sidebar",
        "Quit Meeting Memory",
    ]


def test_symbol_image_views_pass_hit_testing_through_to_the_button():
    views = _build()
    image_view = _buttons(views.root)[0]._mm_image_view
    assert image_view.hitTest_(None) is None


def test_each_button_invokes_its_own_callback_exactly_once():
    calls: list[str] = []
    views = _build(
        on_toggle_recording=lambda: calls.append("record"),
        on_screenshot=lambda: calls.append("shot"),
        on_hide_sidebar=lambda: calls.append("hide"),
        on_quit=lambda: calls.append("quit"),
    )

    for button in _buttons(views.root):
        button.mouseUp_(None)

    assert calls == ["record", "shot", "hide", "quit"]


def test_recording_state_shows_stop_symbol_red_tint_and_timer():
    from dataclasses import replace

    view_model = replace(idle_view_model(), recording=_recording(True, 65))
    views = _build(view_model)

    record = _buttons(views.root)[0]
    assert _symbol(record) == RECORD_ACTIVE_SYMBOL
    assert record._mm_image_view.tint == "systemRed"
    assert record.tooltip == "Stop recording · 01:05"
    timer = next(s for s in views.root.subviews if isinstance(s, FakeNSTextField))
    assert timer.text == "01:05" and timer.isHidden() is False
    assert views.height == compact_size(Orientation.VERTICAL, is_recording=False)[1] + TIMER_HEIGHT


def test_horizontal_recording_reserves_the_timer_beside_the_record_button():
    from dataclasses import replace

    view_model = replace(idle_view_model(), recording=_recording(True, 5))
    views = _build(view_model, orientation=Orientation.HORIZONTAL)

    record, screenshot, _hide, _quit = _buttons(views.root)
    assert screenshot.frame().origin.x == record.frame().origin.x + BUTTON + TIMER_WIDTH + GAP
    assert views.width == compact_size(Orientation.HORIZONTAL, is_recording=False)[0] + TIMER_WIDTH


def test_update_changes_symbol_tint_tooltip_and_timer_in_place():
    views = _build()
    record = views.recording
    timer = next(s for s in views.root.subviews if isinstance(s, FakeNSTextField))
    assert timer.isHidden() is True

    record.update(_recording(True, 3725, warning=True))

    assert _symbol(record) == RECORD_ACTIVE_SYMBOL
    assert record._mm_image_view.tint == "systemOrange"
    assert record.tooltip == "⚠︎ Audio warning · Stop recording · 1:02:05"
    assert timer.text == "1:02:05" and timer.text_color == "systemOrange"

    record.update(_recording(False))
    assert _symbol(record) == RECORD_IDLE_SYMBOL
    assert timer.isHidden() is True and timer.text == ""


def test_update_skips_appkit_when_the_view_is_unchanged():
    views = _build()
    image_view = views.recording._mm_image_view
    before = image_view.image

    views.recording.update(idle_view_model().recording)

    assert image_view.image is before


def test_falls_back_to_text_glyphs_when_sf_symbols_are_unavailable():
    FakeNSImage.available = False
    views = _build()

    record = _buttons(views.root)[0]
    assert record._mm_image_view.image is None
    assert record._mm_glyph.text == "●"
    record.update(_recording(True, 1))
    assert record._mm_glyph.text == "■"


def test_timer_and_tooltip_helpers():
    assert timer_text(_recording(True, 0)) == "00:00"
    assert timer_text(_recording(True, 3600)) == "1:00:00"
    assert record_tooltip(_recording(False)) == "Start recording"

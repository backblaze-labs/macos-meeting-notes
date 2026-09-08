"""Tests for the horizontal (top/bottom-snapped) sidebar layout — see
docs/features/sidebar/completed/06-horizontal-layout.md.
"""

from __future__ import annotations

import pytest
from appkit_fakes import reset_fake_appkit_state
from appkit_geometry_fakes import fake_make_rect
from sidebar_horizontal_fakes import (
    FakeNSPopover,
    FakeNSPopUpButton,
    FakePanel,
    FakeViewModel,
    HFakeNSTextField,
    HFakeNSView,
    HorizontalFakeAppKit,
    RecordingView,
    Row,
)

from meeting_memory.ui.sidebar_geometry import SnapAnchor
from meeting_memory.ui.sidebar_horizontal import (
    PANEL_HEIGHT,
    PANEL_WIDTH,
    build_horizontal,
    popover_edge_for,
    show_overflow_popover,
)


@pytest.fixture(autouse=True)
def _reset_appkit_state():
    reset_fake_appkit_state()
    yield
    reset_fake_appkit_state()


def _build(view_model, **overrides):
    appkit = HorizontalFakeAppKit()
    FakeNSPopover.shown = []
    calls = {"toggle": 0, "overflow": 0}
    kwargs = {
        "on_toggle_recording": lambda: calls.__setitem__("toggle", calls["toggle"] + 1),
        "on_overflow": lambda: calls.__setitem__("overflow", calls["overflow"] + 1),
        **overrides,
    }
    views = build_horizontal(appkit, view_model, **kwargs)
    return appkit, views, calls


def test_full_view_model_renders_record_control_audio_popup_and_overflow():
    view_model = FakeViewModel(
        recording=RecordingView("■ Stop Recording · 00:05"),
        audio_modes=(Row("✓ Full Meeting"), Row("Silent System Only")),
        pending_rows=(Row("task"),),
    )
    _appkit, views, _calls = _build(view_model)

    assert views.root.frame().size.width == PANEL_WIDTH
    assert views.root.frame().size.height == PANEL_HEIGHT
    recording_label = next(v for v in views.recording.subviews if isinstance(v, HFakeNSTextField))
    assert recording_label.text == "■ Stop Recording · 00:05"
    popups = [v for v in views.root.subviews if isinstance(v, FakeNSPopUpButton)]
    assert [item.title for item in popups[0].items] == ["Full Meeting", "Silent System Only"]
    assert popups[0].selected_index == 0


def test_warning_segment_hidden_unless_audio_warning():
    quiet = FakeViewModel(recording=RecordingView("▶ Start Recording", audio_warning=False))
    _appkit, views, _calls = _build(quiet)
    assert views.warning.hidden is True

    warning = FakeViewModel(
        recording=RecordingView("⚠︎ ■ Stop Recording · 00:05", audio_warning=True)
    )
    _appkit, views, _calls = _build(warning)
    assert views.warning.hidden is False


def test_pending_badge_hidden_at_zero_shows_count_otherwise():
    empty = FakeViewModel(recording=RecordingView("▶ Start Recording"), pending_rows=())
    _appkit, views, _calls = _build(empty)
    assert views.pending_badge.hidden is True

    populated = FakeViewModel(
        recording=RecordingView("▶ Start Recording"), pending_rows=(Row("a"), Row("b"))
    )
    _appkit, views, _calls = _build(populated)
    assert views.pending_badge.hidden is False
    assert views.pending_badge.subviews[0].text == "2"  # the label inside the pill


def test_recording_update_changes_label_and_warning_visibility_in_place():
    view_model = FakeViewModel(recording=RecordingView("▶ Start Recording", audio_warning=False))
    _appkit, views, _calls = _build(view_model)

    views.recording.update(RecordingView("⚠︎ ■ Stop Recording · 00:10", audio_warning=True))

    label = next(v for v in views.recording.subviews if isinstance(v, HFakeNSTextField))
    assert label.text == "⚠︎ ■ Stop Recording · 00:10"
    assert views.warning.hidden is False


def test_overflow_click_invokes_on_overflow_exactly_once():
    view_model = FakeViewModel(recording=RecordingView("▶ Start Recording"))
    _appkit, views, calls = _build(view_model)

    assert views.overflow_button is views.root.subviews[-1]
    views.overflow_button.mouseUp_(None)

    assert calls["overflow"] == 1


def test_audio_mode_popup_selection_invokes_the_row_action():
    picked = []
    view_model = FakeViewModel(
        recording=RecordingView("▶ Start Recording"),
        audio_modes=(
            Row("✓ Full Meeting", action=lambda: picked.append("full")),
            Row("Silent System Only", action=lambda: picked.append("silent")),
        ),
    )
    _appkit, views, _calls = _build(view_model)
    popup = next(v for v in views.root.subviews if isinstance(v, FakeNSPopUpButton))

    popup.click(1)

    assert picked == ["silent"]


def test_popover_edge_bottom_opens_upward_top_opens_downward():
    assert popover_edge_for(SnapAnchor.BOTTOM) == "NSMaxYEdge"
    assert popover_edge_for(SnapAnchor.TOP) == "NSMinYEdge"


def test_show_overflow_popover_orders_panel_front_and_uses_the_right_edge():
    appkit = HorizontalFakeAppKit()
    panel = FakePanel()
    overflow_button = HFakeNSView()
    overflow_button._frame = fake_make_rect(0.0, 0.0, 26.0, 22.0)
    content = HFakeNSView()

    popover = show_overflow_popover(
        appkit,
        overflow_button=overflow_button,
        anchor=SnapAnchor.BOTTOM,
        content_view=content,
        panel=panel,
    )

    assert panel.shown is True
    assert popover.content_view_controller.view is content
    assert popover.behavior == appkit.NSPopoverBehaviorTransient
    assert FakeNSPopover.shown[-1][2] == appkit.NSMaxYEdge

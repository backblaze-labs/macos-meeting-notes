"""Fake-AppKit tests for the floating sidebar panel shell."""

from __future__ import annotations

import pytest
from appkit_fakes import (
    FakeAnimationContext,
    FakeAppKit,
    FakeNSWorkspace,
    FakeScreen,
    fake_make_rect,
    reset_fake_appkit_state,
)

from meeting_memory.ui.sidebar_geometry import Orientation, SnapAnchor
from meeting_memory.ui.sidebar_panel import (
    DEFAULT_HORIZONTAL,
    DEFAULT_VERTICAL,
    DRAG_HANDLE_HEIGHT,
    SidebarPanel,
)

SCREEN_RECT = fake_make_rect(0.0, 0.0, 1440.0, 900.0)


@pytest.fixture(autouse=True)
def _reset_appkit_state():
    reset_fake_appkit_state()
    yield
    reset_fake_appkit_state()


def make_panel(*, on_anchor_changed=None) -> tuple[SidebarPanel, FakeAppKit]:
    appkit = FakeAppKit()
    appkit.NSScreen.screens_list = [FakeScreen(SCREEN_RECT)]
    panel = SidebarPanel(appkit=appkit, on_anchor_changed=on_anchor_changed)
    return panel, appkit


def set_frame(panel: SidebarPanel, x: float, y: float, width: float, height: float) -> None:
    panel._panel._frame = fake_make_rect(x, y, width, height)


def test_show_hide_toggle_drive_visibility():
    panel, _ = make_panel()

    assert panel.is_visible is False
    assert panel.toggle() is True
    assert panel.is_visible is True
    panel.hide()
    assert panel.is_visible is False
    panel.show()
    assert panel.is_visible is True
    assert panel.toggle() is False


def test_show_calls_order_front_regardless_never_make_key():
    panel, _ = make_panel()

    panel.show()

    assert panel._panel.order_front_regardless_called is True
    assert panel._panel.made_key_and_ordered_front_called is False


@pytest.mark.parametrize(
    "anchor, frame, expected_orientation",
    [
        (SnapAnchor.LEFT, (20.0, 200.0, 240.0, 460.0), Orientation.VERTICAL),
        (SnapAnchor.RIGHT, (1180.0, 200.0, 240.0, 460.0), Orientation.VERTICAL),
        (SnapAnchor.TOP, (400.0, 420.0, 240.0, 460.0), Orientation.HORIZONTAL),
        (SnapAnchor.BOTTOM, (400.0, 20.0, 240.0, 460.0), Orientation.HORIZONTAL),
    ],
)
def test_drag_end_at_each_edge_produces_right_anchor(anchor, frame, expected_orientation):
    panel, _ = make_panel()
    set_frame(panel, *frame)

    panel._handle_drag_end()

    assert panel.anchor == anchor
    assert panel.orientation == expected_orientation


def test_reorientation_resizes_before_computing_origin():
    panel, _ = make_panel()
    # Top edge 20 pt under the screen top while still vertically sized —
    # forces a reorientation.
    set_frame(panel, 400.0, 900.0 - 20.0 - DEFAULT_VERTICAL[1], *DEFAULT_VERTICAL)

    panel._handle_drag_end()

    final_frame = panel._panel.frame()
    assert (final_frame.size.width, final_frame.size.height) == DEFAULT_HORIZONTAL
    width, height = DEFAULT_HORIZONTAL
    expected_x = SCREEN_RECT.origin.x + SCREEN_RECT.size.width / 2 - width / 2
    expected_y = SCREEN_RECT.origin.y + SCREEN_RECT.size.height - height
    assert final_frame.origin.x == expected_x
    assert final_frame.origin.y == expected_y


def test_drag_end_in_open_space_leaves_panel_free():
    panel, _ = make_panel()
    set_frame(panel, 600.0, 200.0, *DEFAULT_VERTICAL)

    panel._handle_drag_end()

    assert panel.anchor == SnapAnchor.FREE
    final_frame = panel._panel.frame()
    assert (final_frame.origin.x, final_frame.origin.y) == (600.0, 200.0)


def test_screen_parameters_notification_reclamps_shrunken_screen():
    panel, appkit = make_panel()
    set_frame(panel, 1300.0, 800.0, *DEFAULT_VERTICAL)

    shrunken = fake_make_rect(0.0, 0.0, 1000.0, 700.0)
    appkit.NSScreen.screens_list = [FakeScreen(shrunken)]

    panel._handle_screen_change(None)

    final_frame = panel._panel.frame()
    assert final_frame.origin.x <= shrunken.size.width - DEFAULT_VERTICAL[0]
    assert final_frame.origin.y <= shrunken.size.height - DEFAULT_VERTICAL[1]


def test_reduced_motion_skips_animation_context():
    panel, _ = make_panel()
    set_frame(panel, 600.0, 400.0, *DEFAULT_VERTICAL)
    FakeNSWorkspace.reduce_motion = True

    panel._handle_drag_end()

    assert FakeAnimationContext.ran is False
    calls = [name for name, _ in panel._panel.frame_calls]
    assert "setFrame_display_" in calls
    assert "animator" not in calls


def test_on_anchor_changed_fires_once_not_on_redrop():
    changes = []
    panel, _ = make_panel(on_anchor_changed=changes.append)

    set_frame(panel, 20.0, 200.0, 240.0, 460.0)
    panel._handle_drag_end()
    # A second drag back to the same edge: still LEFT, no new callback.
    set_frame(panel, 30.0, 250.0, 240.0, 460.0)
    panel._handle_drag_end()

    assert changes == [SnapAnchor.LEFT]


def test_set_content_view_replaces_rather_than_stacks():
    # Regression guard: plans 05/06 call this on every rebuild, including a
    # section collapse. Only adding a subview leaves every previous copy
    # drawn underneath the new one.
    panel, appkit = make_panel()
    first = appkit.NSView.alloc().initWithFrame_(fake_make_rect(0.0, 0.0, 240.0, 100.0))
    second = appkit.NSView.alloc().initWithFrame_(fake_make_rect(0.0, 0.0, 240.0, 120.0))

    panel.set_content_view(first)
    panel.set_content_view(second)

    # The drag indicator is a persistent subview of the drag view — it's
    # created once at panel construction and never rebuilt, so it stays
    # alongside whatever the current content view is.
    subviews = [
        v
        for v in panel._drag_view.subviews
        if v is panel._drag_indicator or v is panel._drag_strip or v is first or v is second
    ]
    chrome = (panel._drag_indicator, panel._drag_strip)
    assert [v for v in subviews if v not in chrome] == [second]


def test_set_content_view_resizes_the_panel_to_the_content_height():
    # Vertical layout reserves a top drag-handle strip (see
    # sidebar_panel.DRAG_HANDLE_HEIGHT), so the panel is content_height +
    # DRAG_HANDLE_HEIGHT tall — without it the drag view is fully covered
    # by the content's row containers and nothing is grabbable.
    from meeting_memory.ui.sidebar_panel import DRAG_HANDLE_HEIGHT

    panel, appkit = make_panel()
    set_frame(panel, 100.0, 500.0, 240.0, 460.0)

    panel.set_content_view(
        appkit.NSView.alloc().initWithFrame_(fake_make_rect(0.0, 0.0, 240.0, 300.0))
    )

    frame = panel._panel.frame()
    expected_height = 300.0 + DRAG_HANDLE_HEIGHT
    assert frame.size.height == expected_height
    # Top edge pinned: it was 500 + 460 == 960, so new origin is 960 - expected.
    assert frame.origin.y == 960.0 - expected_height
    assert frame.origin.x == 100.0


def test_sharing_type_is_not_forced_and_defaults_to_visible_to_capture():
    # The screenshot/screen-share hiding feature (`setSharingType_(
    # NSWindowSharingNone)`) was removed on request — the panel now appears
    # in shots and shares like any normal window. This regression-guards
    # against silently reintroducing it: the fake NSPanel starts sharing
    # type as `None` (never assigned) and no code touches it.
    panel, _ = make_panel()

    assert panel._panel.sharing_type is None


def test_anchor_round_trips_through_fake_user_defaults():
    panel, appkit = make_panel()
    set_frame(panel, 1180.0, 200.0, 240.0, 460.0)
    panel._handle_drag_end()
    assert panel.anchor == SnapAnchor.RIGHT

    restarted = SidebarPanel(appkit=appkit)

    assert restarted.anchor == SnapAnchor.RIGHT
    assert restarted.orientation == Orientation.VERTICAL


def test_reorientation_animates_to_the_rebuilt_content_size_not_the_default():
    # Regression: the snap animation used to start toward DEFAULT_VERTICAL
    # before on_anchor_changed rebuilt taller content, and the in-flight
    # animation's 460 pt target won — clipping the top rows.
    holder: dict = {}

    def rebuild_tall_content(_anchor) -> None:
        panel = holder["panel"]
        panel.set_content_view(
            panel.appkit.NSView.alloc().initWithFrame_(fake_make_rect(0.0, 0.0, 240.0, 800.0))
        )

    panel, _ = make_panel(on_anchor_changed=rebuild_tall_content)
    holder["panel"] = panel
    set_frame(panel, 400.0, 900.0 - DEFAULT_VERTICAL[1], *DEFAULT_VERTICAL)  # top edge flush
    panel._handle_drag_end()  # -> TOP, horizontal
    assert panel.orientation is Orientation.HORIZONTAL

    set_frame(panel, 20.0, 200.0, *DEFAULT_HORIZONTAL)
    panel._handle_drag_end()  # -> LEFT, back to vertical with 800 pt content

    frame = panel._panel.frame()
    assert frame.size.height == 800.0 + DRAG_HANDLE_HEIGHT
    assert frame.origin.x == 0.0

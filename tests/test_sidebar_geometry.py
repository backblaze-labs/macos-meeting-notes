"""Exhaustive tests for the pure sidebar snap geometry module.

Parametrized over the two screen shapes measured on the owner's machine:
a built-in display (1728x1117 frame, 1728x1084 visible — 33 pt menu bar
inset) and an external display (1920x1080 frame, 1920x1080 visible — no
inset). Assertions use explicit numbers, not the module's own formulas,
so a regression in the formula itself cannot pass by construction.
"""

from __future__ import annotations

import pytest

from meeting_memory.ui.sidebar_geometry import (
    Orientation,
    Rect,
    SnapAnchor,
    clamp_to_visible,
    nearest_anchor,
    orientation_for,
    resolve_drop,
    screen_for,
    snapped_origin,
)

BUILTIN_VISIBLE = Rect(0, 0, 1728, 1084)  # 33 pt menu bar inset already applied
EXTERNAL_VISIBLE = Rect(0, 0, 1920, 1080)  # no inset

VERTICAL_SIZE = (240.0, 420.0)
HORIZONTAL_SIZE = (420.0, 240.0)


# --- orientation_for ---------------------------------------------------


@pytest.mark.parametrize(
    ("anchor", "expected"),
    [
        (SnapAnchor.FREE, Orientation.VERTICAL),
        (SnapAnchor.LEFT, Orientation.VERTICAL),
        (SnapAnchor.RIGHT, Orientation.VERTICAL),
        (SnapAnchor.TOP, Orientation.HORIZONTAL),
        (SnapAnchor.BOTTOM, Orientation.HORIZONTAL),
    ],
)
def test_orientation_for_all_anchors(anchor: SnapAnchor, expected: Orientation) -> None:
    assert orientation_for(anchor) is expected


# --- nearest_anchor ------------------------------------------------------


def _panel_centered_at(cx: float, cy: float, size: tuple[float, float] = (100.0, 100.0)) -> Rect:
    width, height = size
    return Rect(cx - width / 2, cy - height / 2, width, height)


def test_nearest_anchor_free_at_screen_center() -> None:
    panel = _panel_centered_at(BUILTIN_VISIBLE.center_x, BUILTIN_VISIBLE.center_y)
    assert nearest_anchor(panel, BUILTIN_VISIBLE) is SnapAnchor.FREE


@pytest.mark.parametrize(
    ("cx", "cy", "expected"),
    [
        (47.0, 542.0, SnapAnchor.LEFT),
        (1681.0, 542.0, SnapAnchor.RIGHT),
        (864.0, 1037.0, SnapAnchor.TOP),
        (864.0, 47.0, SnapAnchor.BOTTOM),
    ],
)
def test_nearest_anchor_just_inside_threshold(cx: float, cy: float, expected: SnapAnchor) -> None:
    panel = _panel_centered_at(cx, cy)
    assert nearest_anchor(panel, BUILTIN_VISIBLE) is expected


def test_nearest_anchor_free_just_outside_threshold() -> None:
    # Left *edge* 65 pt from the screen's left edge, > SNAP_THRESHOLD (64),
    # and far from every other edge.
    panel = _panel_centered_at(115.0, 542.0)
    assert nearest_anchor(panel, BUILTIN_VISIBLE) is SnapAnchor.FREE


def test_resolve_drop_keeps_the_current_anchor_when_nudged_slightly_away() -> None:
    # Snapped LEFT, then re-grabbed and released 120 pt in: outside the
    # snap threshold but inside the sticky one, so it stays LEFT.
    panel = Rect(120.0, 300.0, 240.0, 460.0)
    anchor, x, y, orientation = resolve_drop(
        panel, [BUILTIN_VISIBLE], current_anchor=SnapAnchor.LEFT
    )
    assert (anchor, x, orientation) == (SnapAnchor.LEFT, 0.0, Orientation.VERTICAL)

    # Dragged well clear (400 pt): the stickiness lets go.
    far = Rect(400.0, 300.0, 240.0, 460.0)
    assert resolve_drop(far, [BUILTIN_VISIBLE], current_anchor=SnapAnchor.LEFT)[0] is (
        SnapAnchor.FREE
    )
    # A free panel gets no stickiness at all.
    assert resolve_drop(panel, [BUILTIN_VISIBLE])[0] is SnapAnchor.FREE


def test_nearest_anchor_measures_the_panel_edge_not_its_center() -> None:
    # A real vertical panel (240x474) sitting flush under the menu bar: its
    # center is 237 pt from the top, its top edge 0 pt. It must snap TOP.
    panel = Rect(744.0, BUILTIN_VISIBLE.height - 474.0, 240.0, 474.0)
    assert nearest_anchor(panel, BUILTIN_VISIBLE) is SnapAnchor.TOP


def test_nearest_anchor_tie_resolves_to_priority_order() -> None:
    # A 200x100 screen where the panel's top and bottom edges are both 30 pt
    # from their screen edges (right is 35, left is 130). LEFT, RIGHT, TOP,
    # BOTTOM priority means TOP wins the top/bottom tie.
    visible = Rect(0, 0, 200, 100)
    panel = _panel_centered_at(185.0, 80.0, size=(100.0, 40.0))
    assert nearest_anchor(panel, visible, threshold=32.0) is SnapAnchor.TOP


# --- snapped_origin --------------------------------------------------------


def test_snapped_origin_free_returns_panel_origin_unchanged() -> None:
    panel = Rect(123.0, 456.0, 240.0, 420.0)
    assert snapped_origin(panel, BUILTIN_VISIBLE, SnapAnchor.FREE) == (123.0, 456.0)


@pytest.mark.parametrize(
    ("visible", "anchor", "expected"),
    [
        (BUILTIN_VISIBLE, SnapAnchor.LEFT, (0.0, 332.0)),
        (BUILTIN_VISIBLE, SnapAnchor.RIGHT, (1488.0, 332.0)),
        (EXTERNAL_VISIBLE, SnapAnchor.LEFT, (0.0, 330.0)),
        (EXTERNAL_VISIBLE, SnapAnchor.RIGHT, (1680.0, 330.0)),
    ],
)
def test_snapped_origin_vertical_anchors_flush_and_centered(
    visible: Rect, anchor: SnapAnchor, expected: tuple[float, float]
) -> None:
    panel = Rect(999.0, 999.0, *VERTICAL_SIZE)  # position irrelevant for non-FREE anchors
    assert snapped_origin(panel, visible, anchor) == expected


@pytest.mark.parametrize(
    ("visible", "anchor", "expected"),
    [
        (EXTERNAL_VISIBLE, SnapAnchor.TOP, (750.0, 840.0)),
        (EXTERNAL_VISIBLE, SnapAnchor.BOTTOM, (750.0, 0.0)),
    ],
)
def test_snapped_origin_horizontal_anchors_flush_and_centered(
    visible: Rect, anchor: SnapAnchor, expected: tuple[float, float]
) -> None:
    panel = Rect(999.0, 999.0, *HORIZONTAL_SIZE)
    assert snapped_origin(panel, visible, anchor) == expected


def test_snapped_origin_top_respects_33pt_inset() -> None:
    # Against visibleFrame (height 1084): y = 1084 - 240 = 844.
    # Against raw frame (height 1117) this would wrongly be 877, sliding the
    # panel 33 pt under the menu bar.
    panel = Rect(999.0, 999.0, *HORIZONTAL_SIZE)
    x, y = snapped_origin(panel, BUILTIN_VISIBLE, SnapAnchor.TOP)
    assert (x, y) == (654.0, 844.0)
    assert y != 877.0


def test_snapped_origin_bottom_flush_and_centered_on_builtin() -> None:
    panel = Rect(999.0, 999.0, *HORIZONTAL_SIZE)
    assert snapped_origin(panel, BUILTIN_VISIBLE, SnapAnchor.BOTTOM) == (654.0, 0.0)


# --- screen_for --------------------------------------------------------


SCREEN_A = Rect(0, 0, 1000, 1000)
SCREEN_B = Rect(1000, 0, 1000, 1000)


def test_screen_for_picks_majority_overlap_screen() -> None:
    panel = Rect(700.0, 400.0, 400.0, 200.0)  # mostly inside A
    assert screen_for(panel, [SCREEN_A, SCREEN_B]) == SCREEN_A


def test_screen_for_straddling_picks_first_on_exact_tie() -> None:
    panel = Rect(900.0, 0.0, 200.0, 200.0)  # exactly half in A, half in B
    assert screen_for(panel, [SCREEN_A, SCREEN_B]) == SCREEN_A


def test_screen_for_zero_overlap_falls_back_to_first_screen() -> None:
    panel = Rect(5000.0, 5000.0, 100.0, 100.0)
    assert screen_for(panel, [SCREEN_A, SCREEN_B]) == SCREEN_A


def test_screen_for_empty_screens_raises() -> None:
    with pytest.raises(ValueError, match="at least one screen"):
        screen_for(Rect(0.0, 0.0, 100.0, 100.0), [])


# --- clamp_to_visible ----------------------------------------------------


def test_clamp_to_visible_fully_offscreen() -> None:
    panel = Rect(-500.0, -500.0, 240.0, 420.0)
    assert clamp_to_visible(panel, BUILTIN_VISIBLE) == (0.0, 0.0)


@pytest.mark.parametrize(
    ("panel", "expected"),
    [
        (Rect(-50.0, 300.0, 240.0, 420.0), (0.0, 300.0)),  # off the left edge
        (Rect(1600.0, 300.0, 240.0, 420.0), (1488.0, 300.0)),  # off the right edge
        (Rect(100.0, 900.0, 240.0, 420.0), (100.0, 664.0)),  # off the top edge
        (Rect(100.0, -100.0, 240.0, 420.0), (100.0, 0.0)),  # off the bottom edge
    ],
)
def test_clamp_to_visible_partly_offscreen(panel: Rect, expected: tuple[float, float]) -> None:
    assert clamp_to_visible(panel, BUILTIN_VISIBLE) == expected


def test_clamp_to_visible_panel_wider_than_screen_pins_to_origin() -> None:
    panel = Rect(500.0, 300.0, 2000.0, 420.0)  # wider than the 1728 pt screen
    assert clamp_to_visible(panel, BUILTIN_VISIBLE) == (0.0, 300.0)


# --- resolve_drop --------------------------------------------------------


def test_resolve_drop_near_external_right_edge() -> None:
    builtin = Rect(0.0, 0.0, 1728.0, 1084.0)
    external = Rect(1728.0, 0.0, 1920.0, 1080.0)
    # Right edge 20 pt from external's right edge, mostly overlapping external.
    panel = Rect(3388.0, 330.0, 240.0, 420.0)
    assert resolve_drop(panel, [builtin, external]) == (
        SnapAnchor.RIGHT,
        3408.0,
        330.0,
        Orientation.VERTICAL,
    )


def test_resolve_drop_near_builtin_top_edge() -> None:
    builtin = Rect(0.0, 0.0, 1728.0, 1084.0)
    external = Rect(1728.0, 0.0, 1920.0, 1080.0)
    # Top edge 20 pt from builtin's top edge, entirely overlapping builtin.
    panel = Rect(654.0, 824.0, 420.0, 240.0)
    assert resolve_drop(panel, [builtin, external]) == (
        SnapAnchor.TOP,
        654.0,
        844.0,
        Orientation.HORIZONTAL,
    )


# --- resize-then-place ordering (gotcha 2) --------------------------------


def test_snapped_origin_requires_resize_before_placement() -> None:
    """A panel about to reorient to horizontal must be resized *before*
    snapped_origin is called — calling it with the stale vertical size
    silently centers against the wrong width."""

    still_vertical = Rect(0.0, 0.0, *VERTICAL_SIZE)  # 240 wide — stale
    resized_horizontal = Rect(0.0, 0.0, *HORIZONTAL_SIZE)  # 420 wide — correct

    wrong_x, _ = snapped_origin(still_vertical, BUILTIN_VISIBLE, SnapAnchor.TOP)
    correct_x, _ = snapped_origin(resized_horizontal, BUILTIN_VISIBLE, SnapAnchor.TOP)

    assert wrong_x == 744.0
    assert correct_x == 654.0
    assert wrong_x != correct_x

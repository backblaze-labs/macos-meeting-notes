"""Pure snap geometry and orientation model for the floating sidebar.

No AppKit import: callers convert `NSRect`/`NSScreen.visibleFrame` to `Rect`
at the boundary. Coordinates follow the AppKit convention — origin at the
bottom-left, y grows up — so `NSWindow.frame` and `NSScreen.visibleFrame`
need no flipping before being passed in.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

SNAP_THRESHOLD = 64.0
# Once snapped, a panel stays snapped unless dragged well clear of its edge:
# a small nudge while re-grabbing it should not drop it into free-float.
STICKY_THRESHOLD = 160.0

_ANCHOR_PRIORITY = ("left", "right", "top", "bottom")


class SnapAnchor(StrEnum):
    FREE = "free"
    LEFT = "left"
    RIGHT = "right"
    TOP = "top"
    BOTTOM = "bottom"


class Orientation(StrEnum):
    VERTICAL = "vertical"
    HORIZONTAL = "horizontal"


@dataclass(frozen=True, slots=True)
class Rect:
    x: float
    y: float
    width: float
    height: float

    @property
    def center_x(self) -> float:
        return self.x + self.width / 2

    @property
    def center_y(self) -> float:
        return self.y + self.height / 2


def orientation_for(anchor: SnapAnchor) -> Orientation:
    """LEFT/RIGHT/FREE -> VERTICAL; TOP/BOTTOM -> HORIZONTAL."""

    if anchor in (SnapAnchor.TOP, SnapAnchor.BOTTOM):
        return Orientation.HORIZONTAL
    return Orientation.VERTICAL


def screen_for(panel: Rect, screens: Sequence[Rect]) -> Rect:
    """The visible frame holding the largest area of `panel`.

    Falls back to screens[0] when there is no overlap at all.
    """

    if not screens:
        raise ValueError("at least one screen is required")

    best = screens[0]
    best_area = -1.0
    for screen in screens:
        area = _overlap_area(panel, screen)
        if area > best_area:
            best = screen
            best_area = area
    return best


def nearest_anchor(panel: Rect, visible: Rect, threshold: float = SNAP_THRESHOLD) -> SnapAnchor:
    """FREE unless one of the panel's edges is within `threshold` of the
    matching screen edge.

    Measured edge-to-edge, not from the panel's center: a 470 pt-tall
    vertical panel could never bring its *center* within 48 pt of the top
    or bottom of the screen without leaving it mostly offscreen, which is
    why top/bottom snapping never triggered from a real drag before this.

    Ties resolve in LEFT, RIGHT, TOP, BOTTOM order (deterministic).
    """

    distances = edge_distances(panel, visible)
    name = min(_ANCHOR_PRIORITY, key=lambda anchor_name: distances[anchor_name])
    if distances[name] > threshold:
        return SnapAnchor.FREE
    return SnapAnchor(name)


def edge_distances(panel: Rect, visible: Rect) -> dict[str, float]:
    """Distance from each panel edge to the matching screen edge."""

    return {
        "left": abs(panel.x - visible.x),
        "right": abs((visible.x + visible.width) - (panel.x + panel.width)),
        "top": abs((visible.y + visible.height) - (panel.y + panel.height)),
        "bottom": abs(panel.y - visible.y),
    }


def snapped_origin(panel: Rect, visible: Rect, anchor: SnapAnchor) -> tuple[float, float]:
    """Flush origin for `anchor`, centered on the perpendicular axis.

    Returns panel's own origin unchanged for FREE. Callers must resize
    `panel` to its target orientation's dimensions *before* calling this —
    otherwise a vertical-sized panel gets centered as if it were still
    vertical while about to be drawn horizontal.
    """

    if anchor is SnapAnchor.FREE:
        return panel.x, panel.y
    if anchor is SnapAnchor.LEFT:
        return visible.x, visible.center_y - panel.height / 2
    if anchor is SnapAnchor.RIGHT:
        return visible.x + visible.width - panel.width, visible.center_y - panel.height / 2
    if anchor is SnapAnchor.TOP:
        return visible.center_x - panel.width / 2, visible.y + visible.height - panel.height
    return visible.center_x - panel.width / 2, visible.y


def clamp_to_visible(panel: Rect, visible: Rect) -> tuple[float, float]:
    """Pull a fully- or partly-offscreen panel back inside `visible`.

    Used after a display is disconnected or resolution changes.
    """

    max_x = visible.x + max(visible.width - panel.width, 0.0)
    max_y = visible.y + max(visible.height - panel.height, 0.0)
    x = min(max(panel.x, visible.x), max_x)
    y = min(max(panel.y, visible.y), max_y)
    return x, y


def resolve_drop(
    panel: Rect,
    screens: Sequence[Rect],
    threshold: float = SNAP_THRESHOLD,
    *,
    current_anchor: SnapAnchor = SnapAnchor.FREE,
    sticky_threshold: float = STICKY_THRESHOLD,
) -> tuple[SnapAnchor, float, float, Orientation]:
    """One call for plan 02's mouse-up: pick screen, pick anchor, place, orient.

    `current_anchor` makes an existing snap sticky: if the drop lands in
    free space but the panel is still within `sticky_threshold` of the edge
    it was snapped to, it re-snaps there instead of floating.
    """

    visible = screen_for(panel, screens)
    anchor = nearest_anchor(panel, visible, threshold)
    if anchor is SnapAnchor.FREE and current_anchor is not SnapAnchor.FREE:
        if edge_distances(panel, visible)[current_anchor.value] <= sticky_threshold:
            anchor = current_anchor
    x, y = snapped_origin(panel, visible, anchor)
    return anchor, x, y, orientation_for(anchor)


def _overlap_area(a: Rect, b: Rect) -> float:
    width = max(0.0, min(a.x + a.width, b.x + b.width) - max(a.x, b.x))
    height = max(0.0, min(a.y + a.height, b.y + b.height) - max(a.y, b.y))
    return width * height

"""Sidebar colors and header chrome, taken from the app icon.

`MeetingMemory.icns` is a navy-to-teal gradient tile with an off-white
robot. The panel's header block uses that gradient; section headers, the
idle recording control, and glyph buttons use the teal as an accent.
Everything else stays system-colored so light/dark mode and accessibility
settings keep working.
"""

from __future__ import annotations

from typing import Any

NAVY = (0.07, 0.16, 0.23)  # icon top-left
TEAL = (0.06, 0.38, 0.38)  # icon bottom-right; the accent

_header_view_classes: dict[int, type] = {}


def accent_color(appkit: Any) -> Any:
    return appkit.NSColor.colorWithSRGBRed_green_blue_alpha_(*TEAL, 1.0)


def navy_color(appkit: Any) -> Any:
    return appkit.NSColor.colorWithSRGBRed_green_blue_alpha_(*NAVY, 1.0)


def on_header_color(appkit: Any, alpha: float = 1.0) -> Any:
    """Text/glyph color on top of the header gradient."""

    return appkit.NSColor.colorWithSRGBRed_green_blue_alpha_(0.94, 0.94, 0.94, alpha)


def title_font(appkit: Any) -> Any:
    return appkit.NSFont.boldSystemFontOfSize_(13.0)


def header_font(appkit: Any) -> Any:
    return appkit.NSFont.systemFontOfSize_weight_(11.0, appkit.NSFontWeightSemibold)


def control_font(appkit: Any) -> Any:
    return appkit.NSFont.systemFontOfSize_weight_(13.0, appkit.NSFontWeightSemibold)


def header_view(appkit: Any, frame: Any, *, solid: bool = False, clear: bool = False) -> Any:
    """A navy→teal gradient block (solid navy when `solid`; nothing drawn when
    `clear`, for a grab area that must not read as a border).

    Passes hit-testing through (`hitTest_` returns None) so a press on the
    header reaches the drag view underneath and moves the panel — the
    header *is* the grab area, not just the slim strip above it.
    """

    view = _header_view_class(appkit).alloc().initWithFrame_(frame)
    view._mm_style = "clear" if clear else "solid" if solid else "gradient"
    return view


def pill_view(appkit: Any, frame: Any) -> Any:
    """A rounded teal pill (the horizontal bar's pending-count badge)."""

    view = _header_view_class(appkit).alloc().initWithFrame_(frame)
    view._mm_style = "pill"
    return view


def _header_view_class(appkit: Any) -> type:
    # One Objective-C subclass per NSView base, same caching rule as
    # `sidebar_widgets._clickable_view_class`.
    base = appkit.NSView
    cached = _header_view_classes.get(id(base))
    if cached is not None:
        return cached

    class SidebarHeaderView(base):
        def hitTest_(self, point):
            del point
            return None

        def drawRect_(self, rect):
            del rect
            style = getattr(self, "_mm_style", "gradient")
            if style == "clear":
                return
            if style == "pill":
                radius = self.bounds().size.height / 2
                accent_color(appkit).setFill()
                appkit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                    self.bounds(), radius, radius
                ).fill()
                return
            start = navy_color(appkit)
            end = start if style == "solid" else accent_color(appkit)
            gradient = appkit.NSGradient.alloc().initWithStartingColor_endingColor_(start, end)
            gradient.drawInRect_angle_(self.bounds(), 0.0)

    _header_view_classes[id(base)] = SidebarHeaderView
    return SidebarHeaderView

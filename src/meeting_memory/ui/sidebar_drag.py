"""Drag-handle view for the sidebar panel.

`setMovableByWindowBackground_` is one line but gives no mouse-up signal, and
the panel must snap on release — so dragging is tracked here by hand, on a
vibrancy-backed `NSVisualEffectView` subclass built dynamically against an
injected `appkit` namespace (real `AppKit` in production, a fake in tests).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from meeting_memory.ui.sidebar_theme import header_view, on_header_color

CORNER_RADIUS = 14.0

_drag_handle_view_classes: dict[int, type] = {}


def make_drag_handle_view(appkit: Any, *, on_drag_end: Callable[[], None]) -> Any:
    """Build and return one drag-tracking, vibrancy-backed content view.

    Tracks drag delta in screen coordinates (`NSEvent.mouseLocation()`), not
    window-local coordinates — the window moves under the cursor mid-drag, so
    window-local coordinates drift and produce runaway movement.
    """

    view = _drag_handle_view_class(appkit).alloc().init()
    view._mm_on_drag_end = on_drag_end
    view.setMaterial_(appkit.NSVisualEffectMaterialHUDWindow)
    view.setBlendingMode_(appkit.NSVisualEffectBlendingModeBehindWindow)
    view.setState_(appkit.NSVisualEffectStateActive)
    view.setWantsLayer_(True)
    view.layer().setCornerRadius_(CORNER_RADIUS)
    view.layer().setMasksToBounds_(True)
    return view


def _drag_handle_view_class(appkit: Any) -> type:
    """One Objective-C subclass per `NSVisualEffectView` base. pyobjc
    registers a real Objective-C class the first time a Python class
    subclasses it; redefining a same-named class on a second call raises
    `objc.error: ... overriding existing Objective-C class` — see the
    identical fix in `sidebar_widgets.py`'s `_clickable_view_class`.

    Keyed on the base class object (stable across `_real_appkit()` calls),
    not the `appkit` namespace instance — production builds a fresh wrapper
    per `SidebarPanel`, so keying on the wrapper would never hit the cache.
    """

    base = appkit.NSVisualEffectView
    key = id(base)
    cached = _drag_handle_view_classes.get(key)
    if cached is not None:
        return cached

    class DragHandleView(appkit.NSVisualEffectView):
        def mouseDown_(self, event) -> None:
            del event
            window = self.window()
            if window is None:
                return
            origin = window.frame().origin
            location = appkit.NSEvent.mouseLocation()
            self._mm_drag_start = (location.x - origin.x, location.y - origin.y)

        def mouseDragged_(self, event) -> None:
            del event
            window = self.window()
            start = getattr(self, "_mm_drag_start", None)
            if window is None or start is None:
                return
            location = appkit.NSEvent.mouseLocation()
            window.setFrameOrigin_(appkit.NSMakePoint(location.x - start[0], location.y - start[1]))

        def mouseUp_(self, event) -> None:
            del event
            self._mm_drag_start = None
            callback = getattr(self, "_mm_on_drag_end", None)
            if callback is not None:
                callback()

    _drag_handle_view_classes[key] = DragHandleView
    return DragHandleView


_grabber_label_classes: dict[int, type] = {}


def make_drag_indicator(appkit: Any) -> Any:
    """A tiny `⠿` grabber label for the vertical panel's reserved drag
    strip, so the strip reads as draggable instead of as empty padding.

    Hit-testing is disabled on it (`hitTest_` returns None): a plain label
    would otherwise swallow the mouse-down at the exact spot that invites a
    drag, and the drag view underneath would never see it.
    """

    indicator = _grabber_label_class(appkit).labelWithString_("⠿")
    indicator.setTextColor_(on_header_color(appkit, 0.7))
    indicator.setAlignment_(1)  # NSTextAlignmentCenter
    return indicator


def make_drag_strip(appkit: Any) -> Any:
    """Solid navy backing for the strip, so it reads as the top of the
    header block rather than a bare margin. Pass-through like the grabber."""

    return header_view(appkit, appkit.NSMakeRect(0.0, 0.0, 0.0, 0.0), solid=True)


def position_drag_indicator(
    appkit: Any, indicator: Any, strip: Any, width: float, height: float, handle_height: float
) -> None:
    """Lay the strip along the top edge of a `width` x `height` panel and
    center the grabber in it; pass `handle_height=0` to park both out of sight."""

    if handle_height <= 0:
        indicator.setFrame_(appkit.NSMakeRect(0.0, 0.0, 0.0, 0.0))
        strip.setFrame_(appkit.NSMakeRect(0.0, 0.0, 0.0, 0.0))
        return
    strip.setFrame_(appkit.NSMakeRect(0.0, height - handle_height, width, handle_height))
    grabber_width = min(60.0, width - 8.0)  # the compact panel is only 44 pt wide
    indicator.setFrame_(
        appkit.NSMakeRect(
            (width - grabber_width) / 2,
            height - handle_height + 1.0,
            grabber_width,
            handle_height - 2.0,
        )
    )


def _grabber_label_class(appkit: Any) -> type:
    # Same one-subclass-per-base caching as `_drag_handle_view_class` above.
    base = appkit.NSTextField
    key = id(base)
    cached = _grabber_label_classes.get(key)
    if cached is not None:
        return cached

    class GrabberLabel(appkit.NSTextField):
        def hitTest_(self, point):
            del point
            return None

    _grabber_label_classes[key] = GrabberLabel
    return GrabberLabel

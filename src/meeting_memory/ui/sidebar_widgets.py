"""Click-tracking view primitive shared by the sidebar's content builders.

Built against an injected `appkit` namespace (real AppKit in production, a
fake in tests), so this module never imports AppKit itself.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

_clickable_view_classes: dict[int, type] = {}


def clickable_view(appkit: Any, on_click: Callable[[], None] | None, frame: Any) -> Any:
    """An `NSView` that invokes `on_click` on mouse-up; a plain view when
    `on_click` is None so a disabled control has no click target at all."""

    if on_click is None:
        return appkit.NSView.alloc().initWithFrame_(frame)
    view = _clickable_view_class(appkit).alloc().initWithFrame_(frame)
    view._mm_on_click = on_click
    return view


def _clickable_view_class(appkit: Any) -> type:
    """One Objective-C subclass per `NSView` base, reused across every button.
    pyobjc registers a real Objective-C class the first time a Python class
    subclasses `NSView`; redefining a same-named class on every call raises
    `objc.error: ... overriding existing Objective-C class`. The callback is
    per-instance state instead of a per-class closure.

    Keyed on the base class object (stable across `real_appkit()` calls),
    not the `appkit` namespace instance — production builds a fresh wrapper
    per `SidebarPanel`, so keying on the wrapper would never hit the cache.
    """

    base = appkit.NSView
    key = id(base)
    cached = _clickable_view_classes.get(key)
    if cached is not None:
        return cached

    class ClickableView(appkit.NSView):
        def mouseUp_(self, event) -> None:
            del event
            callback = getattr(self, "_mm_on_click", None)
            if callback is not None:
                callback()

    _clickable_view_classes[key] = ClickableView
    return ClickableView

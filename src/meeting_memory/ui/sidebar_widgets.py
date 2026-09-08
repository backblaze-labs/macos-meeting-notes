"""Row/section/separator primitives for the sidebar's vertical layout.

Views are built from duck-typed `RowView`/`RecordingView`-shaped objects (the
frozen dataclasses plan 04's `ui/sidebar_view_model.py` defines), accessed
only by attribute — this module never imports that one. That keeps it
buildable and testable against local fixtures ahead of plan 04 landing.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from meeting_memory.ui.sidebar_theme import accent_color, control_font, header_font

ROW_HEIGHT = 26.0
SECTION_HEADER_HEIGHT = 24.0
PANEL_WIDTH = 240.0
SEPARATOR_HEIGHT = 1.0
_ROW_INSET = 12.0
_LABEL_HEIGHT = 18.0


def row(appkit: Any, view: Any, y: float, width: float = PANEL_WIDTH) -> Any:
    """One row. Disabled rows get no click target and secondary label color
    but keep their tooltip — same rule as today's `_menu_item(callback=None)`."""

    action = view.action if view.enabled else None
    container = _clickable_container(appkit, action, y, width, ROW_HEIGHT)
    container.addSubview_(_make_label(appkit, view.label, width, enabled=view.enabled))
    container.setToolTip_(view.tooltip)
    return container


def recording_row(
    appkit: Any, view: Any, y: float, width: float, on_click: Callable[[], None]
) -> Any:
    """Exposes `.update(view)` for the 1 Hz in-place tick — no rebuild."""

    container = _clickable_container(appkit, on_click, y, width, ROW_HEIGHT)
    label_view = _make_label(appkit, view.label, width, enabled=True, font=control_font(appkit))
    _apply_recording_style(appkit, label_view, view)
    container.addSubview_(label_view)
    shown = [view]

    def update(new_view: Any) -> None:
        if new_view == shown[0]:
            return  # idle label is constant; skip the per-second AppKit round-trip
        shown[0] = new_view
        label_view.setStringValue_(new_view.label)
        _apply_recording_style(appkit, label_view, new_view)

    container.update = update
    return container


def section_header(
    appkit: Any,
    title: str,
    expanded: bool,
    y: float,
    on_toggle: Callable[[], None],
    width: float = PANEL_WIDTH,
) -> Any:
    glyph = "▾" if expanded else "▸"  # ▾ / ▸
    container = _clickable_container(appkit, on_toggle, y, width, SECTION_HEADER_HEIGHT)
    container.addSubview_(header_label(appkit, f"{glyph} {title}", width))
    return container


def header_label(appkit: Any, text: str, width: float) -> Any:
    """Section-heading text: small, semibold, in the icon's teal."""

    return _make_label(
        appkit, text, width, enabled=True, font=header_font(appkit), color=accent_color(appkit)
    )


def separator(appkit: Any, y: float, width: float = PANEL_WIDTH) -> Any:
    return appkit.NSView.alloc().initWithFrame_(appkit.NSMakeRect(0.0, y, width, SEPARATOR_HEIGHT))


def label_row(
    appkit: Any, text: str, y: float, width: float = PANEL_WIDTH, height: float = ROW_HEIGHT
) -> Any:
    """A plain, non-interactive labeled row — a title bar or a fixed
    (never-collapsible, never-empty) section heading."""

    container = appkit.NSView.alloc().initWithFrame_(appkit.NSMakeRect(0.0, y, width, height))
    container.addSubview_(_make_label(appkit, text, width, enabled=True))
    return container


_clickable_view_classes: dict[int, type] = {}


def _clickable_container(
    appkit: Any, on_click: Callable[[], None] | None, y: float, width: float, height: float
) -> Any:
    frame = appkit.NSMakeRect(0.0, y, width, height)
    if on_click is None:
        return appkit.NSView.alloc().initWithFrame_(frame)

    view = _clickable_view_class(appkit).alloc().initWithFrame_(frame)
    view._mm_on_click = on_click
    return view


def _clickable_view_class(appkit: Any) -> type:
    """One Objective-C subclass per `NSView` base, reused across every row.
    pyobjc registers a real Objective-C class the first time a Python class
    subclasses `NSView`; redefining a same-named class on every call (once
    per row, on every rebuild) raises `objc.error: ... overriding existing
    Objective-C class`. The callback is per-instance state instead of a
    per-class closure.

    Keyed on the base class object (stable across `_real_appkit()` calls),
    not the `appkit` namespace instance — production builds a fresh wrapper
    per `SidebarPanel`, so keying on the wrapper would never hit the cache.
    """

    base = appkit.NSView
    key = id(base)
    cached = _clickable_view_classes.get(key)
    if cached is not None:
        return cached

    class ClickableRow(appkit.NSView):
        def mouseUp_(self, event) -> None:
            del event
            callback = getattr(self, "_mm_on_click", None)
            if callback is not None:
                callback()

    _clickable_view_classes[key] = ClickableRow
    return ClickableRow


def _make_label(
    appkit: Any,
    text: str,
    width: float,
    *,
    enabled: bool,
    font: Any = None,
    color: Any = None,
) -> Any:
    label = appkit.NSTextField.labelWithString_(text)
    label.setFrame_(appkit.NSMakeRect(_ROW_INSET, 4.0, width - 2 * _ROW_INSET, _LABEL_HEIGHT))
    if color is None:
        color = appkit.NSColor.labelColor() if enabled else appkit.NSColor.secondaryLabelColor()
    label.setTextColor_(color)
    if font is not None:
        label.setFont_(font)
    label.setLineBreakMode_(appkit.NSLineBreakByTruncatingTail)
    return label


def _apply_warning_color(appkit: Any, label_view: Any, audio_warning: bool) -> None:
    label_view.setTextColor_(
        appkit.NSColor.systemOrangeColor() if audio_warning else appkit.NSColor.labelColor()
    )


def _apply_recording_style(appkit: Any, label_view: Any, view: Any) -> None:
    """Warning beats everything (orange); a live recording reads in the
    system label color; the idle "Start" control is the teal accent."""

    if view.audio_warning:
        label_view.setTextColor_(appkit.NSColor.systemOrangeColor())
    elif getattr(view, "is_recording", False):
        label_view.setTextColor_(appkit.NSColor.labelColor())
    else:
        label_view.setTextColor_(accent_color(appkit))

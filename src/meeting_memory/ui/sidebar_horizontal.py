"""Horizontal (top/bottom-snapped) sidebar layout: a compact control bar,
with everything else behind an overflow button that opens plan 05's full
vertical section stack as a popover.

See docs/features/sidebar/completed/06-horizontal-layout.md.

Duck-typed against `SidebarViewModel`/`RowView`/`RecordingView` (plan 04),
same convention `sidebar_vertical.py` and `sidebar_widgets.py` already use —
this module never imports `sidebar_view_model.py`.

Where this reuses `sidebar_widgets.py` and where it doesn't: every widget in
that module positions itself at a fixed `x=0` for vertical stacking, which
does not fit a row of side-by-side segments. Rather than force that shape,
each segment here is its own `NSView`/control positioned explicitly along
the bar — but the click-detection trick (`_clickable_container`'s NSView
subclass overriding `mouseUp_`) and recording-color rule
(`_apply_recording_style`) are imported directly rather than re-implemented,
per gotcha 1 — the two layouts still can't drift on those two behaviors.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from meeting_memory.ui.sidebar_geometry import SnapAnchor
from meeting_memory.ui.sidebar_theme import (
    accent_color,
    control_font,
    header_font,
    header_view,
    on_header_color,
    pill_view,
)
from meeting_memory.ui.sidebar_widgets import _apply_recording_style, _clickable_container

PANEL_WIDTH = 620.0
PANEL_HEIGHT = 56.0  # a strip, not a slab: one control row plus breathing room

_MARGIN = 8.0
_BRAND_WIDTH = 44.0  # gradient block at the left end, carrying the ⠿ grip
_RECORD_WIDTH = 210.0
_WARNING_WIDTH = 110.0
_AUDIO_POPUP_WIDTH = 150.0
_BADGE_WIDTH = 26.0
_OVERFLOW_WIDTH = 26.0
_CONTROL_HEIGHT = 22.0
_CONTROL_Y = (PANEL_HEIGHT - _CONTROL_HEIGHT) / 2

_ACTION_TARGET_CLASS: Any = None
_popup_classes: dict[int, type] = {}


@dataclass(frozen=True, slots=True)
class HorizontalViews:
    root: Any
    recording: Any  # .update(RecordingView) — also toggles the warning segment
    warning: Any
    pending_badge: Any
    overflow_button: Any  # pass to show_overflow_popover's overflow_button= param


def build_horizontal(
    appkit: Any,
    view_model: Any,
    *,
    on_toggle_recording: Callable[[], None],
    on_overflow: Callable[[], None],
) -> HorizontalViews:
    """Build the compact bar. `view_model` is a `SidebarViewModel`.

    `recording.update(new_view)` is the single per-tick hook the caller needs
    (gotcha 2): it updates both the recording label and the paired warning
    segment's visibility, so `ui/tray.py`'s 1 Hz tick stays orientation-
    agnostic — it calls the same method whether the vertical or horizontal
    layout is showing.
    """

    root = appkit.NSView.alloc().initWithFrame_(
        appkit.NSMakeRect(0.0, 0.0, PANEL_WIDTH, PANEL_HEIGHT)
    )
    root.addSubview_(_brand_block(appkit))
    x = _BRAND_WIDTH + _MARGIN

    warning = _warning_segment(appkit, view_model.recording.audio_warning)
    recording = _recording_control(appkit, view_model.recording, warning, on_toggle_recording)
    _position(appkit, recording, x, _RECORD_WIDTH)
    root.addSubview_(recording)
    x += _RECORD_WIDTH + _MARGIN

    _position(appkit, warning, x, _WARNING_WIDTH)
    root.addSubview_(warning)
    x += _WARNING_WIDTH + _MARGIN

    root.addSubview_(_audio_mode_popup(appkit, view_model.audio_modes, x))
    x += _AUDIO_POPUP_WIDTH + _MARGIN

    pending_badge = _pending_badge(appkit, len(view_model.pending.rows))
    _position(appkit, pending_badge, x, _BADGE_WIDTH)
    root.addSubview_(pending_badge)
    x += _BADGE_WIDTH + _MARGIN

    overflow = _clickable_container(appkit, on_overflow, 0.0, _OVERFLOW_WIDTH, _CONTROL_HEIGHT)
    overflow.addSubview_(_glyph_label(appkit, "⋯", _OVERFLOW_WIDTH))
    _position(appkit, overflow, x, _OVERFLOW_WIDTH)
    root.addSubview_(overflow)

    return HorizontalViews(
        root=root,
        recording=recording,
        warning=warning,
        pending_badge=pending_badge,
        overflow_button=overflow,
    )


def popover_edge_for(anchor: SnapAnchor) -> str:
    """Which edge of the `⋯` button the overflow popover should open from.

    A bar snapped to the bottom of the screen must open its popover upward,
    or it renders offscreen (gotcha 6) — and vice versa for the top.
    """

    if anchor is SnapAnchor.BOTTOM:
        return "NSMaxYEdge"
    return "NSMinYEdge"  # TOP, and any other anchor this layout could show under


def show_overflow_popover(
    appkit: Any,
    *,
    overflow_button: Any,
    anchor: SnapAnchor,
    content_view: Any,
    panel: Any,
) -> Any:
    """Show `content_view` (plan 05's vertical stack) in a transient popover
    anchored to the overflow button, edge picked by `popover_edge_for`.

    Gotcha 7: a non-activating panel's popover can misbehave unless the
    panel is ordered front immediately before showing it. `panel` is
    `SidebarPanel` itself (its public `.show()`), not the raw `NSPanel` —
    that keeps `SidebarPanel`'s own `is_visible` bookkeeping correct too.
    """

    panel.show()

    controller = appkit.NSViewController.alloc().init()
    controller.setView_(content_view)

    popover = appkit.NSPopover.alloc().init()
    popover.setContentViewController_(controller)
    popover.setBehavior_(appkit.NSPopoverBehaviorTransient)

    edge_name = popover_edge_for(anchor)
    popover.showRelativeToRect_ofView_preferredEdge_(
        overflow_button.bounds(), overflow_button, getattr(appkit, edge_name)
    )
    return popover


def _position(appkit: Any, view: Any, x: float, width: float) -> None:
    view.setFrame_(appkit.NSMakeRect(x, _CONTROL_Y, width, _CONTROL_HEIGHT))


def _brand_block(appkit: Any, height: float = PANEL_HEIGHT) -> Any:
    """The bar's left end: the icon's navy→teal gradient with the ⠿ grip.
    `header_view` passes hit-testing through, so pressing it drags the bar."""

    block = header_view(appkit, appkit.NSMakeRect(0.0, 0.0, _BRAND_WIDTH, height))
    grip = appkit.NSTextField.labelWithString_("⠿")
    grip.setFrame_(appkit.NSMakeRect(0.0, (height - _CONTROL_HEIGHT) / 2, _BRAND_WIDTH, 22.0))
    grip.setTextColor_(on_header_color(appkit, 0.85))
    grip.setFont_(control_font(appkit))
    grip.setAlignment_(1)  # NSTextAlignmentCenter
    block.addSubview_(grip)
    return block


def _glyph_label(appkit: Any, text: str, width: float) -> Any:
    label = appkit.NSTextField.labelWithString_(text)
    label.setFrame_(appkit.NSMakeRect(0.0, 0.0, width, _CONTROL_HEIGHT))
    label.setTextColor_(accent_color(appkit))
    label.setFont_(control_font(appkit))
    label.setAlignment_(1)
    return label


def _recording_control(
    appkit: Any, view: Any, warning_view: Any, on_click: Callable[[], None]
) -> Any:
    container = _clickable_container(appkit, on_click, 0.0, _RECORD_WIDTH, _CONTROL_HEIGHT)
    label = appkit.NSTextField.labelWithString_(view.label)
    label.setFrame_(appkit.NSMakeRect(0.0, 0.0, _RECORD_WIDTH, _CONTROL_HEIGHT))
    label.setLineBreakMode_(appkit.NSLineBreakByTruncatingTail)
    label.setFont_(control_font(appkit))
    _apply_recording_style(appkit, label, view)
    container.addSubview_(label)
    shown = [view]

    def update(new_view: Any) -> None:
        if new_view == shown[0]:
            return  # same rule as sidebar_widgets.recording_row
        shown[0] = new_view
        label.setStringValue_(new_view.label)
        _apply_recording_style(appkit, label, new_view)
        warning_view.setHidden_(not new_view.audio_warning)

    container.update = update
    return container


def _warning_segment(appkit: Any, audio_warning: bool) -> Any:
    label = appkit.NSTextField.labelWithString_("⚠︎ Mic silent")
    label.setFrame_(appkit.NSMakeRect(0.0, 0.0, _WARNING_WIDTH, _CONTROL_HEIGHT))
    label.setHidden_(not audio_warning)
    return label


def _pending_badge(appkit: Any, count: int) -> Any:
    """Teal pill with the pending-task count; hidden at zero."""

    pill = pill_view(appkit, appkit.NSMakeRect(0.0, 0.0, _BADGE_WIDTH, _CONTROL_HEIGHT))
    label = appkit.NSTextField.labelWithString_(str(count))
    label.setFrame_(appkit.NSMakeRect(0.0, 3.0, _BADGE_WIDTH, 16.0))
    label.setTextColor_(on_header_color(appkit))
    label.setFont_(header_font(appkit))
    label.setAlignment_(1)
    pill.addSubview_(label)
    pill.setHidden_(count == 0)
    return pill


def _audio_mode_popup(appkit: Any, audio_modes: tuple[Any, ...], x: float) -> Any:
    popup = (
        _popup_class(appkit)
        .alloc()
        .initWithFrame_pullsDown_(
            appkit.NSMakeRect(x, _CONTROL_Y, _AUDIO_POPUP_WIDTH, _CONTROL_HEIGHT), False
        )
    )
    selected_index = 0
    for index, mode_row in enumerate(audio_modes):
        popup.addItemWithTitle_(mode_row.label.removeprefix("✓ "))
        if mode_row.label.startswith("✓ "):
            selected_index = index
    popup.selectItemAtIndex_(selected_index)

    def handle_selection() -> None:
        audio_modes[popup.indexOfSelectedItem()].action()

    target = _make_action_target(appkit, handle_selection)
    popup.setTarget_(target)
    popup.setAction_("invoke:")
    popup._meeting_memory_target = target  # retained: setTarget_ is weak in AppKit
    return popup


def _popup_class(appkit: Any) -> type:
    # A Python subclass, not a bare `appkit.NSPopUpButton`: pyobjc rejects
    # ad-hoc attributes on real AppKit instances, and the popup must own its
    # target (found in plan 06's manual pass). Cached per base like
    # `sidebar_widgets._clickable_view_class`.
    base = appkit.NSPopUpButton
    cached = _popup_classes.get(id(base))
    if cached is not None:
        return cached

    class AudioModePopUp(base):
        pass

    _popup_classes[id(base)] = AudioModePopUp
    return AudioModePopUp


def _action_target_class(appkit: Any) -> Any:
    # Defined once, not per call: pyobjc registers ObjC classes by name and
    # raises on a second registration (see plan 03's findings).
    global _ACTION_TARGET_CLASS
    if _ACTION_TARGET_CLASS is None:

        class _ActionTarget(appkit.NSObject):
            def invoke_(self, sender: Any) -> None:
                handler = getattr(self, "_meeting_memory_handler", None)
                if handler is not None:
                    handler()

        _ACTION_TARGET_CLASS = _ActionTarget
    return _ACTION_TARGET_CLASS


def _make_action_target(appkit: Any, handler: Callable[[], None]) -> Any:
    target = _action_target_class(appkit).alloc().init()
    target._meeting_memory_handler = handler
    return target

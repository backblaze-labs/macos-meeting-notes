"""Compact icon-only sidebar content: record/stop, screenshot, quit.

Three SF Symbol buttons and nothing else, so the panel is as small as it can
be while every function stays one click away. Snapped to the left or right
edge the buttons stack vertically; snapped to the top or bottom (or floating
free) they sit in a row behind a `⠿` grip. While recording the record button
turns into a red stop button and a small elapsed timer appears beside it;
everything else the old panel listed lives in the status-item menu
(`ui/status_menu.py`).

Duck-typed against `RecordingView`/`SidebarViewModel` and an injected
`appkit` namespace, like every sidebar module.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from meeting_memory.ui import menu
from meeting_memory.ui.sidebar_geometry import Orientation
from meeting_memory.ui.sidebar_theme import accent_color, control_font, header_view, on_header_color
from meeting_memory.ui.sidebar_widgets import clickable_view

BUTTON = 32.0
GAP = 4.0
INSET = 6.0
GRIP_WIDTH = 18.0  # horizontal bar's drag handle; the vertical panel uses its top strip
TIMER_HEIGHT = 14.0  # vertical: under the record button while recording
TIMER_WIDTH = 46.0  # horizontal: right of the record button while recording
SYMBOL_POINT_SIZE = 18.0
RECORD_IDLE_SYMBOL = "record.circle"
RECORD_ACTIVE_SYMBOL = "stop.circle.fill"
SCREENSHOT_SYMBOL = "camera.fill"
QUIT_SYMBOL = "power"
FALLBACK_GLYPHS = {
    RECORD_IDLE_SYMBOL: "●",
    RECORD_ACTIVE_SYMBOL: "■",
    SCREENSHOT_SYMBOL: "📷",
    QUIT_SYMBOL: "⏻",
}
RECORD_IDLE_TOOLTIP = "Start recording"
SCREENSHOT_TOOLTIP = f"Take screenshot ({menu.SCREENSHOT_SHORTCUT})"
QUIT_TOOLTIP = "Quit Meeting Memory"

_symbol_view_classes: dict[int, type] = {}


@dataclass(frozen=True, slots=True)
class CompactViews:
    root: Any
    recording: Any  # .update(RecordingView) — button glyph, tint, tooltip, timer
    width: float
    height: float


def compact_size(orientation: Orientation, *, is_recording: bool) -> tuple[float, float]:
    buttons = 3 * BUTTON + 2 * GAP
    if orientation is Orientation.HORIZONTAL:
        timer = TIMER_WIDTH if is_recording else 0.0
        return GRIP_WIDTH + INSET + buttons + timer + INSET, BUTTON + 2 * INSET
    timer = TIMER_HEIGHT if is_recording else 0.0
    return BUTTON + 2 * INSET, INSET + buttons + timer + INSET


def build_compact(
    appkit: Any,
    view_model: Any,
    *,
    orientation: Orientation,
    on_toggle_recording: Callable[[], None],
    on_screenshot: Callable[[], None],
    on_quit: Callable[[], None],
) -> CompactViews:
    view = view_model.recording
    horizontal = orientation is Orientation.HORIZONTAL
    width, height = compact_size(orientation, is_recording=view.is_recording)
    root = appkit.NSView.alloc().initWithFrame_(appkit.NSMakeRect(0.0, 0.0, width, height))
    if horizontal:
        root.addSubview_(_grip(appkit, height))

    record_origin, timer_frame, shot_origin, quit_origin = _layout(
        horizontal, height, view.is_recording
    )
    record = _icon_button(appkit, record_origin, on_toggle_recording)
    timer = _timer_label(appkit, timer_frame)
    _apply_recording_state(appkit, record, timer, view)
    root.addSubview_(record)
    root.addSubview_(timer)
    screenshot = _icon_button(appkit, shot_origin, on_screenshot)
    _set_symbol(appkit, screenshot, SCREENSHOT_SYMBOL, appkit.NSColor.labelColor())
    screenshot.setToolTip_(SCREENSHOT_TOOLTIP)
    root.addSubview_(screenshot)
    quit_button = _icon_button(appkit, quit_origin, on_quit)
    _set_symbol(appkit, quit_button, QUIT_SYMBOL, appkit.NSColor.secondaryLabelColor())
    quit_button.setToolTip_(QUIT_TOOLTIP)
    root.addSubview_(quit_button)

    shown = [view]

    def update(new_view: Any) -> None:
        if new_view == shown[0]:
            return  # idle state is constant; skip the per-second AppKit round-trip
        shown[0] = new_view
        _apply_recording_state(appkit, record, timer, new_view)

    record.update = update
    return CompactViews(root=root, recording=record, width=width, height=height)


def record_tooltip(view: Any) -> str:
    if not view.is_recording:
        return RECORD_IDLE_TOOLTIP
    prefix = "⚠︎ Audio warning · " if view.audio_warning else ""
    return f"{prefix}Stop recording · {timer_text(view)}"


def timer_text(view: Any) -> str:
    minutes, seconds = divmod(max(0, view.duration_seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def _layout(
    horizontal: bool, height: float, is_recording: bool
) -> tuple[tuple[float, float], Any, tuple[float, float], tuple[float, float]]:
    if horizontal:
        x = GRIP_WIDTH + INSET
        timer_width = TIMER_WIDTH if is_recording else 0.0
        timer = (x + BUTTON, INSET, timer_width, BUTTON)
        shot_x = x + BUTTON + timer_width + GAP
        return (x, INSET), timer, (shot_x, INSET), (shot_x + BUTTON + GAP, INSET)
    quit_y = INSET
    shot_y = quit_y + BUTTON + GAP
    timer_height = TIMER_HEIGHT if is_recording else 0.0
    timer = (0.0, shot_y + BUTTON + GAP, BUTTON + 2 * INSET, timer_height)
    return (INSET, shot_y + BUTTON + GAP + timer_height), timer, (INSET, shot_y), (INSET, quit_y)


def _icon_button(appkit: Any, origin: tuple[float, float], on_click: Callable[[], None]) -> Any:
    button = clickable_view(appkit, on_click, appkit.NSMakeRect(*origin, BUTTON, BUTTON))
    image_view = (
        _symbol_view_class(appkit)
        .alloc()
        .initWithFrame_(appkit.NSMakeRect(0.0, 0.0, BUTTON, BUTTON))
    )
    image_view.setImageScaling_(appkit.NSImageScaleProportionallyDown)
    button.addSubview_(image_view)
    button._mm_image_view = image_view
    return button


def _set_symbol(appkit: Any, button: Any, name: str, tint: Any) -> None:
    image = symbol_image(appkit, name)
    image_view = button._mm_image_view
    if image is None:
        _replace_with_glyph(appkit, button, FALLBACK_GLYPHS[name], tint)
        return
    image_view.setImage_(image)
    image_view.setContentTintColor_(tint)


def symbol_image(appkit: Any, name: str) -> Any:
    image = appkit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, name)
    if image is None:
        return None  # pre-Big Sur AppKit: caller falls back to a text glyph
    configuration = appkit.NSImageSymbolConfiguration.configurationWithPointSize_weight_(
        SYMBOL_POINT_SIZE, appkit.NSFontWeightRegular
    )
    return image.imageWithSymbolConfiguration_(configuration)


def _replace_with_glyph(appkit: Any, button: Any, glyph: str, tint: Any) -> None:
    existing = getattr(button, "_mm_glyph", None)
    if existing is None:
        existing = appkit.NSTextField.labelWithString_(glyph)
        existing.setFrame_(appkit.NSMakeRect(0.0, 6.0, BUTTON, 20.0))
        existing.setFont_(control_font(appkit))
        existing.setAlignment_(1)  # NSTextAlignmentCenter
        button.addSubview_(existing)
        button._mm_glyph = existing
    existing.setStringValue_(glyph)
    existing.setTextColor_(tint)


def _apply_recording_state(appkit: Any, record: Any, timer: Any, view: Any) -> None:
    if view.audio_warning:
        tint = appkit.NSColor.systemOrangeColor()
    elif view.is_recording:
        tint = appkit.NSColor.systemRedColor()
    else:
        tint = accent_color(appkit)
    _set_symbol(
        appkit, record, RECORD_ACTIVE_SYMBOL if view.is_recording else RECORD_IDLE_SYMBOL, tint
    )
    record.setToolTip_(record_tooltip(view))
    timer.setStringValue_(timer_text(view) if view.is_recording else "")
    timer.setHidden_(not view.is_recording)
    timer.setTextColor_(
        appkit.NSColor.systemOrangeColor() if view.audio_warning else appkit.NSColor.labelColor()
    )


def _timer_label(appkit: Any, frame: tuple[float, float, float, float]) -> Any:
    label = appkit.NSTextField.labelWithString_("")
    label.setFrame_(appkit.NSMakeRect(*frame))
    label.setFont_(
        appkit.NSFont.monospacedDigitSystemFontOfSize_weight_(10.0, appkit.NSFontWeightSemibold)
    )
    label.setAlignment_(1)
    label.setLineBreakMode_(appkit.NSLineBreakByTruncatingTail)
    return label


def _grip(appkit: Any, height: float) -> Any:
    """Gradient block with the `⠿` grip; `header_view` passes hit-testing
    through, so pressing it drags the bar."""

    block = header_view(appkit, appkit.NSMakeRect(0.0, 0.0, GRIP_WIDTH, height))
    grip = appkit.NSTextField.labelWithString_("⠿")
    grip.setFrame_(appkit.NSMakeRect(0.0, (height - 22.0) / 2, GRIP_WIDTH, 22.0))
    grip.setTextColor_(on_header_color(appkit, 0.85))
    grip.setFont_(control_font(appkit))
    grip.setAlignment_(1)
    block.addSubview_(grip)
    return block


def _symbol_view_class(appkit: Any) -> type:
    """An `NSImageView` that passes hit-testing through to the clickable
    button underneath (an image view would otherwise swallow the mouse-up).
    One subclass per base class, same rule as `sidebar_widgets.py`."""

    base = appkit.NSImageView
    cached = _symbol_view_classes.get(id(base))
    if cached is not None:
        return cached

    class SymbolView(base):
        def hitTest_(self, point):
            del point
            return None

    _symbol_view_classes[id(base)] = SymbolView
    return SymbolView

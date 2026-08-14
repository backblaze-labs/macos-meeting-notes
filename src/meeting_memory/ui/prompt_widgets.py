"""Small native AppKit building blocks for Notes customization."""

from __future__ import annotations

from typing import Any


def label(
    text: str,
    frame: tuple[int, int, int, int],
    *,
    size: float = 13,
    bold: bool = False,
    color: Any | None = None,
    selectable: bool = False,
) -> Any:
    from AppKit import NSFont, NSMakeRect, NSTextField

    field = NSTextField.alloc().initWithFrame_(NSMakeRect(*frame))
    field.setStringValue_(text)
    field.setBezeled_(False)
    field.setDrawsBackground_(False)
    field.setEditable_(False)
    field.setSelectable_(selectable)
    font = NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size)
    field.setFont_(font)
    if color is not None:
        field.setTextColor_(color)
    return field


def text_field(
    value: str,
    frame: tuple[int, int, int, int],
    *,
    placeholder: str = "",
) -> Any:
    from AppKit import NSMakeRect, NSTextField

    field = NSTextField.alloc().initWithFrame_(NSMakeRect(*frame))
    field.setStringValue_(value)
    if placeholder:
        field.setPlaceholderString_(placeholder)
    return field


def button(title: str, frame: tuple[int, int, int, int]) -> Any:
    from AppKit import NSBezelStyleRounded, NSButton, NSMakeRect

    control = NSButton.alloc().initWithFrame_(NSMakeRect(*frame))
    control.setTitle_(title)
    control.setBezelStyle_(NSBezelStyleRounded)
    return control


def checkbox(title: str, frame: tuple[int, int, int, int], *, checked: bool) -> Any:
    from AppKit import (
        NSButton,
        NSButtonTypeSwitch,
        NSControlStateValueOff,
        NSControlStateValueOn,
        NSMakeRect,
    )

    control = NSButton.alloc().initWithFrame_(NSMakeRect(*frame))
    control.setButtonType_(NSButtonTypeSwitch)
    control.setTitle_(title)
    control.setState_(NSControlStateValueOn if checked else NSControlStateValueOff)
    return control


def text_editor(
    value: str,
    frame: tuple[int, int, int, int],
    *,
    editable: bool,
    fixed_pitch: bool,
    size: float = 12,
) -> tuple[Any, Any]:
    from AppKit import NSFont, NSMakeRect, NSScrollView, NSTextView

    _, _, width, height = frame
    text_view = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))
    text_view.setString_(value)
    text_view.setEditable_(editable)
    text_view.setSelectable_(True)
    text_view.setRichText_(False)
    font = (
        NSFont.userFixedPitchFontOfSize_(size)
        if fixed_pitch
        else NSFont.systemFontOfSize_(size)
    )
    text_view.setFont_(font)
    text_view.setHorizontallyResizable_(False)
    text_view.setVerticallyResizable_(True)
    if hasattr(text_view, "setTextContainerInset_"):
        text_view.setTextContainerInset_((8, 8))
    _disable_smart_replacements(text_view)

    scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(*frame))
    scroll.setDocumentView_(text_view)
    scroll.setHasVerticalScroller_(True)
    scroll.setHasHorizontalScroller_(False)
    scroll.setAutohidesScrollers_(True)
    scroll.setBorderType_(2)
    return scroll, text_view


def separator(frame: tuple[int, int, int, int]) -> Any:
    from AppKit import NSBox, NSBoxSeparator, NSMakeRect

    box = NSBox.alloc().initWithFrame_(NSMakeRect(*frame))
    box.setBoxType_(NSBoxSeparator)
    return box


def bind(control: Any, target: Any, action: str) -> None:
    control.setTarget_(target)
    control.setAction_(action)


def _disable_smart_replacements(text_view: Any) -> None:
    for selector in (
        "setAutomaticQuoteSubstitutionEnabled_",
        "setAutomaticDashSubstitutionEnabled_",
        "setAutomaticTextReplacementEnabled_",
    ):
        setter = getattr(text_view, selector, None)
        if callable(setter):
            setter(False)

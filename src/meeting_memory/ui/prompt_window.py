"""Native window composition for template-based Notes customization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from meeting_memory.config.notes_template import NotesPromptDocument
from meeting_memory.types.notes_profile import NotesProfile, NotesProfileKind
from meeting_memory.ui.prompt_advanced_page import AdvancedPageViews, build_advanced_page
from meeting_memory.ui.prompt_template_page import TemplatePageViews, build_template_page
from meeting_memory.ui.prompt_widgets import button, label, separator

WINDOW_WIDTH = 940
WINDOW_HEIGHT = 700


@dataclass(frozen=True, slots=True)
class PromptWindowViews:
    window: Any
    page_selector: Any
    templates: TemplatePageViews
    advanced: AdvancedPageViews
    error: Any
    restore: Any
    cancel: Any
    save: Any


def build_prompt_window(document: NotesPromptDocument, profile: NotesProfile) -> PromptWindowViews:
    from AppKit import (
        NSBackingStoreBuffered,
        NSColor,
        NSMakeRect,
        NSSegmentedControl,
        NSSegmentSwitchTrackingSelectOne,
        NSView,
        NSWindow,
        NSWindowStyleMaskClosable,
        NSWindowStyleMaskTitled,
    )

    window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(0, 0, WINDOW_WIDTH, WINDOW_HEIGHT),
        NSWindowStyleMaskTitled | NSWindowStyleMaskClosable,
        NSBackingStoreBuffered,
        False,
    )
    window.setTitle_("Notes Customization")
    window.setReleasedWhenClosed_(False)
    window.center()
    root = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, WINDOW_WIDTH, WINDOW_HEIGHT))
    window.setContentView_(root)

    selector = NSSegmentedControl.alloc().initWithFrame_(NSMakeRect(326, 654, 288, 28))
    selector.setSegmentCount_(2)
    selector.setLabel_forSegment_("Templates", 0)
    selector.setLabel_forSegment_("Advanced", 1)
    selector.setTrackingMode_(NSSegmentSwitchTrackingSelectOne)
    selected_page = 1 if profile.kind is NotesProfileKind.CUSTOM else 0
    selector.setSelectedSegment_(selected_page)
    root.addSubview_(selector)
    root.addSubview_(separator((0, 640, WINDOW_WIDTH, 1)))

    templates = build_template_page(profile)
    advanced = build_advanced_page(profile, document.instructions)
    templates.page.setHidden_(selected_page != 0)
    advanced.page.setHidden_(selected_page != 1)
    root.addSubview_(templates.page)
    root.addSubview_(advanced.page)

    root.addSubview_(separator((0, 54, WINDOW_WIDTH, 1)))
    restore = button("Restore Classic", (18, 14, 126, 30))
    cancel = button("Cancel", (708, 14, 94, 30))
    save = button("Save Profile", (812, 14, 110, 30))
    save.setKeyEquivalent_("\r")
    cancel.setKeyEquivalent_("\x1b")
    window.setDefaultButtonCell_(save.cell())
    error = label(
        "",
        (158, 11, 534, 38),
        size=11,
        color=NSColor.systemRedColor(),
    )
    error.setHidden_(True)
    for control in (restore, error, cancel, save):
        root.addSubview_(control)

    return PromptWindowViews(window, selector, templates, advanced, error, restore, cancel, save)

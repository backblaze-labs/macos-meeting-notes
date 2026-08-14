"""Native window composition for the Notes customization workspace."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from meeting_memory.config.notes_template import NotesPromptDocument, NotesVisualLayout
from meeting_memory.ui.prompt_layout_rows import (
    SectionRowViews,
    build_section_rows,
    placeholder_visual_layout,
)
from meeting_memory.ui.prompt_widgets import (
    button,
    checkbox,
    label,
    separator,
    text_editor,
    text_field,
)

WINDOW_WIDTH = 860
WINDOW_HEIGHT = 620


@dataclass(frozen=True, slots=True)
class LayoutPageViews:
    page: Any
    visual: Any
    advanced: Any
    document_title: Any
    sections: tuple[SectionRowViews, ...]
    include_source: Any
    include_date: Any
    preview: Any
    advanced_editor: Any
    open_advanced: Any
    close_advanced: Any


@dataclass(frozen=True, slots=True)
class PromptWindowViews:
    window: Any
    page_selector: Any
    instructions_page: Any
    instructions_editor: Any
    layout: LayoutPageViews
    error: Any
    restore: Any
    cancel: Any
    save: Any


def build_prompt_window(
    document: NotesPromptDocument,
    visual_layout: NotesVisualLayout | None,
) -> PromptWindowViews:
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

    selector = NSSegmentedControl.alloc().initWithFrame_(NSMakeRect(286, 574, 288, 28))
    selector.setSegmentCount_(2)
    selector.setLabel_forSegment_("AI Instructions", 0)
    selector.setLabel_forSegment_("Report Layout", 1)
    selector.setTrackingMode_(NSSegmentSwitchTrackingSelectOne)
    selector.setSelectedSegment_(1)
    root.addSubview_(selector)
    root.addSubview_(separator((0, 560, WINDOW_WIDTH, 1)))

    instructions_page, instructions_editor = _build_instructions_page(document)
    root.addSubview_(instructions_page)
    instructions_page.setHidden_(True)

    layout = _build_layout_page(document, visual_layout)
    root.addSubview_(layout.page)

    root.addSubview_(separator((0, 54, WINDOW_WIDTH, 1)))
    restore = button("Restore Defaults", (18, 14, 128, 30))
    cancel = button("Cancel", (628, 14, 94, 30))
    save = button("Save Changes", (728, 14, 114, 30))
    save.setKeyEquivalent_("\r")
    cancel.setKeyEquivalent_("\x1b")
    window.setDefaultButtonCell_(save.cell())
    error = label(
        "",
        (158, 17, 454, 22),
        size=11,
        color=NSColor.systemRedColor(),
    )
    error.setHidden_(True)
    for control in (restore, error, cancel, save):
        root.addSubview_(control)

    return PromptWindowViews(
        window,
        selector,
        instructions_page,
        instructions_editor,
        layout,
        error,
        restore,
        cancel,
        save,
    )


def _build_instructions_page(document: NotesPromptDocument) -> tuple[Any, Any]:
    from AppKit import NSColor, NSMakeRect, NSView

    page = NSView.alloc().initWithFrame_(NSMakeRect(0, 55, WINDOW_WIDTH, 505))
    _add(
        page,
        label("Tell the AI what good notes look like", (24, 458, 500, 24), size=16, bold=True),
        label(
            "Write content and privacy guidance. Report structure is configured separately.",
            (24, 436, 670, 20),
            size=12,
            color=NSColor.secondaryLabelColor(),
        ),
        label(
            "Sent to Anthropic",
            (24, 399, 135, 20),
            size=12,
            bold=True,
            color=NSColor.systemBlueColor(),
        ),
        label(
            "These instructions and a speaker-confirmed transcript excerpt leave this Mac "
            "only when Notes runs.",
            (158, 399, 670, 20),
            size=11,
            color=NSColor.secondaryLabelColor(),
        ),
    )
    scroll, editor = text_editor(
        document.instructions,
        (24, 28, 812, 354),
        editable=True,
        fixed_pitch=False,
        size=13,
    )
    page.addSubview_(scroll)
    return page, editor


def _build_layout_page(
    document: NotesPromptDocument,
    visual_layout: NotesVisualLayout | None,
) -> LayoutPageViews:
    from AppKit import NSColor, NSMakeRect, NSView

    page = NSView.alloc().initWithFrame_(NSMakeRect(0, 55, WINDOW_WIDTH, 505))
    _add(
        page,
        label("Shape the report your way", (24, 458, 420, 24), size=16, bold=True),
        label(
            "Rename and reorder sections, choose metadata, and review the result before saving.",
            (24, 436, 680, 20),
            size=12,
            color=NSColor.secondaryLabelColor(),
        ),
        label(
            "Stays on this Mac",
            (708, 458, 128, 20),
            size=11,
            bold=True,
            color=NSColor.systemGreenColor(),
        ),
    )

    visual = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, WINDOW_WIDTH, 425))
    advanced = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, WINDOW_WIDTH, 425))
    page.addSubview_(visual)
    page.addSubview_(advanced)

    layout = visual_layout or placeholder_visual_layout()
    document_title = text_field(layout.title, (24, 352, 382, 26))
    _add(
        visual,
        label("Document title", (24, 382, 180, 18), size=11, bold=True),
        document_title,
        label("Sections", (24, 320, 180, 18), size=11, bold=True),
    )
    rows = build_section_rows(visual, layout)
    include_source = checkbox(
        "Source transcript link",
        (24, 94, 220, 22),
        checked=layout.include_source,
    )
    include_date = checkbox("Meeting date", (24, 68, 220, 22), checked=layout.include_date)
    open_advanced = button("Advanced Markdown…", (24, 20, 156, 30))
    _add(
        visual,
        label("Metadata", (24, 122, 180, 18), size=11, bold=True),
        include_source,
        include_date,
        open_advanced,
        separator((424, 18, 1, 382)),
        label("Preview", (444, 382, 120, 18), size=11, bold=True),
        label(
            "notes.md",
            (746, 382, 90, 18),
            size=11,
            color=NSColor.secondaryLabelColor(),
        ),
    )
    preview_scroll, preview = text_editor(
        "",
        (444, 20, 392, 352),
        editable=False,
        fixed_pitch=False,
        size=12,
    )
    visual.addSubview_(preview_scroll)

    close_advanced = button("Use Visual Editor", (680, 382, 156, 30))
    _add(
        advanced,
        label("Advanced Markdown template", (24, 388, 300, 22), size=13, bold=True),
        label(
            "Generated: {summary}, {decisions}, {action_items}\n"
            "Metadata: {date}, {source_transcript}, {calendar_title}, "
            "{duration_minutes}, {meeting_id}",
            (24, 344, 640, 36),
            size=10,
            color=NSColor.secondaryLabelColor(),
        ),
        close_advanced,
    )
    advanced_scroll, advanced_editor = text_editor(
        document.report_template,
        (24, 20, 812, 312),
        editable=True,
        fixed_pitch=True,
        size=12,
    )
    advanced.addSubview_(advanced_scroll)
    advanced.setHidden_(visual_layout is not None)
    visual.setHidden_(visual_layout is None)

    return LayoutPageViews(
        page,
        visual,
        advanced,
        document_title,
        rows,
        include_source,
        include_date,
        preview,
        advanced_editor,
        open_advanced,
        close_advanced,
    )
def _add(parent: Any, *children: Any) -> None:
    for child in children:
        parent.addSubview_(child)

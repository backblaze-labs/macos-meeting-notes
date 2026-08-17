"""Native advanced section builder for Notes customization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from meeting_memory.types.notes_profile import NotesProfile
from meeting_memory.ui.prompt_preview import update_notes_profile_preview
from meeting_memory.ui.prompt_widgets import (
    button,
    checkbox,
    label,
    popup_button,
    separator,
    text_editor,
    text_field,
)


@dataclass(frozen=True, slots=True)
class AdvancedPageViews:
    page: Any
    report_title: Any
    user_name: Any
    section_selector: Any
    add_section: Any
    remove_section: Any
    move_up: Any
    move_down: Any
    section_title: Any
    audience: Any
    output_format: Any
    guidance: Any
    include_source: Any
    include_date: Any
    instructions: Any
    preview: Any


def build_advanced_page(profile: NotesProfile, instructions: str) -> AdvancedPageViews:
    from AppKit import NSColor, NSMakeRect, NSView

    page = NSView.alloc().initWithFrame_(NSMakeRect(0, 55, 940, 585))
    _add(
        page,
        label("Build your own report", (28, 534, 360, 26), size=18, bold=True),
        label(
            "Define each section's purpose, audience, and Markdown format.",
            (28, 510, 500, 20),
            size=12,
            color=NSColor.secondaryLabelColor(),
        ),
        separator((448, 24, 1, 482)),
    )

    report_title = text_field(profile.report_title, (28, 462, 388, 27))
    user_name = text_field(
        _user_name(profile), (28, 404, 388, 27), placeholder="Optional until a section uses Only me"
    )
    _add(
        page,
        label("Report title", (28, 491, 160, 18), size=11, bold=True),
        report_title,
        label("Your name", (28, 433, 160, 18), size=11, bold=True),
        user_name,
    )

    section_selector = popup_button(
        tuple(section.title for section in profile.sections), (28, 342, 236, 28)
    )
    add_section = button("+", (270, 342, 34, 28))
    remove_section = button("−", (306, 342, 34, 28))
    move_up = button("↑", (344, 342, 34, 28))
    move_down = button("↓", (382, 342, 34, 28))
    _add(
        page,
        label("Sections", (28, 375, 160, 18), size=11, bold=True),
        section_selector,
        add_section,
        remove_section,
        move_up,
        move_down,
    )

    section = profile.sections[0]
    section_title = text_field(section.title, (28, 286, 388, 27))
    audience = popup_button(("Whole meeting", "Each participant", "Only me"), (28, 228, 188, 28))
    output_format = popup_button(
        ("Paragraph", "Bullet list", "Task checklist"), (228, 228, 188, 28)
    )
    _add(
        page,
        label("Section title", (28, 315, 160, 18), size=11, bold=True),
        section_title,
        label("Focus", (28, 257, 120, 18), size=11, bold=True),
        audience,
        label("Format", (228, 257, 120, 18), size=11, bold=True),
        output_format,
        label("What should this section capture?", (28, 199, 260, 18), size=11, bold=True),
    )
    guidance_scroll, guidance = text_editor(
        section.instructions, (28, 82, 388, 110), editable=True, fixed_pitch=False, size=12
    )
    page.addSubview_(guidance_scroll)
    include_source = checkbox(
        "Source transcript", (28, 46, 172, 22), checked=profile.include_source
    )
    include_date = checkbox("Meeting date", (216, 46, 150, 22), checked=profile.include_date)
    _add(page, include_source, include_date)

    _add(
        page,
        label("General AI guidance", (476, 491, 220, 18), size=11, bold=True),
        label(
            "Applies to every section and is sent with the confirmed transcript.",
            (476, 470, 420, 18),
            size=10,
            color=NSColor.secondaryLabelColor(),
        ),
    )
    instructions_scroll, instructions_editor = text_editor(
        instructions, (476, 324, 430, 136), editable=True, fixed_pitch=False, size=12
    )
    page.addSubview_(instructions_scroll)
    _add(page, label("Live preview", (476, 292, 160, 18), size=11, bold=True))
    preview_scroll, preview = text_editor(
        "", (476, 46, 430, 236), editable=False, fixed_pitch=False, size=12
    )
    page.addSubview_(preview_scroll)
    update_notes_profile_preview(preview, profile)

    return AdvancedPageViews(
        page,
        report_title,
        user_name,
        section_selector,
        add_section,
        remove_section,
        move_up,
        move_down,
        section_title,
        audience,
        output_format,
        guidance,
        include_source,
        include_date,
        instructions_editor,
        preview,
    )


def _user_name(profile: NotesProfile) -> str:
    variable = profile.variable_for("user_name")
    return "" if variable is None else variable.value


def _add(parent: Any, *children: Any) -> None:
    for child in children:
        parent.addSubview_(child)

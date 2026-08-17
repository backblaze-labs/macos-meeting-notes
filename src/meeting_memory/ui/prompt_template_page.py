"""Native template chooser for Notes customization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from meeting_memory.types.notes_profile import NotesProfile
from meeting_memory.ui.prompt_preview import update_notes_profile_preview
from meeting_memory.ui.prompt_widgets import button, label, radio_button, text_editor, text_field


@dataclass(frozen=True, slots=True)
class TemplatePageViews:
    page: Any
    classic: Any
    personal: Any
    user_name: Any
    user_name_label: Any
    user_name_help: Any
    preview: Any
    customize: Any


def build_template_page(profile: NotesProfile) -> TemplatePageViews:
    from AppKit import NSColor, NSMakeRect, NSView

    page = NSView.alloc().initWithFrame_(NSMakeRect(0, 55, 940, 585))
    _add(
        page,
        label("Start with a useful recipe", (28, 534, 420, 26), size=18, bold=True),
        label(
            "Choose what the AI should produce. You can fine-tune every section in Advanced.",
            (28, 510, 600, 20),
            size=12,
            color=NSColor.secondaryLabelColor(),
        ),
    )
    classic = radio_button("Classic meeting notes", (28, 444, 300, 24), selected=False)
    personal = radio_button("Personal focus", (28, 340, 300, 24), selected=False)
    _add(
        page,
        classic,
        label(
            "A concise summary, explicit decisions, and action items for everyone.",
            (50, 414, 360, 38),
            size=12,
            color=NSColor.secondaryLabelColor(),
        ),
        personal,
        label(
            "Bullet updates by participant, followed by only the tasks assigned to you.",
            (50, 310, 360, 38),
            size=12,
            color=NSColor.secondaryLabelColor(),
        ),
    )
    user_name_label = label("Your name", (50, 268, 120, 18), size=11, bold=True)
    user_name = text_field("", (50, 235, 330, 27), placeholder="For example, Eduardo")
    user_name_help = label(
        "Required so Meeting Memory can separate your tasks from everyone else's.",
        (50, 207, 350, 32),
        size=10,
        color=NSColor.secondaryLabelColor(),
    )
    customize = button("Customize in Advanced →", (50, 148, 190, 30))
    _add(page, user_name_label, user_name, user_name_help, customize)

    _add(
        page,
        label("Preview", (458, 466, 120, 20), size=12, bold=True),
        label(
            "What the next notes.md will look like",
            (458, 444, 320, 18),
            size=11,
            color=NSColor.secondaryLabelColor(),
        ),
    )
    preview_scroll, preview = text_editor(
        "", (458, 112, 448, 324), editable=False, fixed_pitch=False, size=12
    )
    page.addSubview_(preview_scroll)
    update_notes_profile_preview(preview, profile)
    return TemplatePageViews(
        page,
        classic,
        personal,
        user_name,
        user_name_label,
        user_name_help,
        preview,
        customize,
    )


def _add(parent: Any, *children: Any) -> None:
    for child in children:
        parent.addSubview_(child)

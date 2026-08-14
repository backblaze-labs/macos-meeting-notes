"""Section rows used by the visual Notes report layout editor."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from meeting_memory.config.notes_template import (
    NotesVisualLayout,
    NotesVisualSection,
)
from meeting_memory.ui.prompt_widgets import button, label, text_field


@dataclass(frozen=True, slots=True)
class SectionRowViews:
    title: Any
    kind: Any
    move_up: Any
    move_down: Any


def build_section_rows(
    parent: Any,
    layout: NotesVisualLayout,
) -> tuple[SectionRowViews, ...]:
    from AppKit import NSColor

    rows: list[SectionRowViews] = []
    for index, section in enumerate(layout.sections):
        y = 278 - index * 56
        title = text_field(section.heading, (24, y, 300, 24))
        kind = label(
            _section_kind(section.key),
            (24, y - 18, 300, 16),
            size=10,
            color=NSColor.secondaryLabelColor(),
        )
        up = button("↑", (332, y, 34, 25))
        down = button("↓", (372, y, 34, 25))
        up.setTag_(index * 2)
        down.setTag_(index * 2 + 1)
        for control in (title, kind, up, down):
            parent.addSubview_(control)
        rows.append(SectionRowViews(title, kind, up, down))
    return tuple(rows)


def placeholder_visual_layout() -> NotesVisualLayout:
    return NotesVisualLayout(
        "Meeting Notes",
        tuple(
            NotesVisualSection(key, heading)
            for key, heading in (
                ("summary", "Summary"),
                ("decisions", "Decisions"),
                ("action_items", "Action Items"),
            )
        ),
    )


def _section_kind(key: str) -> str:
    return {
        "summary": "Generated summary",
        "decisions": "Generated decisions",
        "action_items": "Generated action items",
    }[key]

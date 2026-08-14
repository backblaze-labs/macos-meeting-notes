"""Pure round-trip tests for the native visual Notes layout editor."""

from __future__ import annotations

import pytest

from meeting_memory.config.defaults import DEFAULT_NOTES_REPORT_TEMPLATE
from meeting_memory.config.notes_template import (
    NotesVisualLayout,
    NotesVisualSection,
    parse_visual_notes_layout,
    render_visual_notes_layout,
)


def test_default_report_layout_round_trips_through_visual_model() -> None:
    layout = parse_visual_notes_layout(DEFAULT_NOTES_REPORT_TEMPLATE)

    assert layout == NotesVisualLayout(
        "Meeting Notes",
        (
            NotesVisualSection("summary", "Summary"),
            NotesVisualSection("decisions", "Decisions"),
            NotesVisualSection("action_items", "Action Items"),
        ),
        include_source=True,
        include_date=False,
    )
    assert render_visual_notes_layout(layout) == DEFAULT_NOTES_REPORT_TEMPLATE.strip()


def test_visual_layout_preserves_custom_titles_order_and_metadata() -> None:
    layout = NotesVisualLayout(
        "Project Atlas Sync",
        (
            NotesVisualSection("action_items", "Commitments"),
            NotesVisualSection("summary", "What Changed"),
            NotesVisualSection("decisions", "Decision Log"),
        ),
        include_source=False,
        include_date=True,
    )

    rendered = render_visual_notes_layout(layout)

    assert parse_visual_notes_layout(rendered) == layout
    assert rendered.index("{action_items}") < rendered.index("{summary}")
    assert "**Date:** {date}" in rendered
    assert "{source_transcript}" not in rendered


def test_advanced_markdown_remains_valid_without_becoming_visual() -> None:
    custom = """# Brief

Read this first.

## Summary
{summary}

## Decisions
{decisions}

## Actions
{action_items}
"""

    assert parse_visual_notes_layout(custom) is None


@pytest.mark.parametrize("value", ["", "Bad {summary}", "Two\nLines"])
def test_visual_layout_rejects_ambiguous_titles(value: str) -> None:
    layout = NotesVisualLayout(
        value,
        (
            NotesVisualSection("summary", "Summary"),
            NotesVisualSection("decisions", "Decisions"),
            NotesVisualSection("action_items", "Action Items"),
        ),
    )

    with pytest.raises(ValueError, match="document title"):
        render_visual_notes_layout(layout)

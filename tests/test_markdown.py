"""Tests for meeting markdown rendering."""

from __future__ import annotations

from datetime import UTC, datetime

from meeting_memory.service.markdown import render_meeting_markdown
from meeting_memory.types.meeting import MeetingMeta
from meeting_memory.types.summary import ActionItem, SummaryResult
from meeting_memory.types.transcript import TranscriptResult, TranscriptSegment


def test_render_meeting_markdown_contains_frontmatter_and_ordered_sections() -> None:
    meta = MeetingMeta(
        slug="2026-06-10_09-00_product-sync",
        started_at=datetime(2026, 6, 10, 9, 0, tzinfo=UTC),
        calendar_title="Product Sync",
        duration_minutes=42,
    )
    transcript = TranscriptResult(
        assemblyai_id="tx-123",
        segments=(
            TranscriptSegment("Speaker A", 5, "We should ship the demo."),
            TranscriptSegment("Speaker B", 12, "I can send notes."),
        ),
    )
    summary = SummaryResult(
        summary="The team agreed to ship the demo.",
        decisions=("Ship the demo",),
        action_items=(ActionItem(owner="Alex", task="Send notes", due_date="Friday"),),
    )

    markdown = render_meeting_markdown(meta, transcript, summary)

    assert markdown.startswith("---\n")
    assert 'id: "2026-06-10_09-00_product-sync"' in markdown
    assert 'date: "2026-06-10T09:00:00+00:00"' in markdown
    assert 'participants: ["Speaker A", "Speaker B"]' in markdown
    assert "summary_status: \"ok\"" in markdown
    assert "b2_status: \"pending\"" in markdown
    assert "# Product Sync" in markdown
    assert "**Date:** 2026-06-10 09:00" in markdown
    assert "- [ ] Alex: Send notes (Due: Friday)" in markdown
    assert "**Speaker A** (0:00:05): We should ship the demo." in markdown

    assert markdown.index("## Summary") < markdown.index("## Decisions")
    assert markdown.index("## Decisions") < markdown.index("## Action Items")
    assert markdown.index("## Action Items") < markdown.index("## Transcript")


def test_render_meeting_markdown_uses_placeholders_for_empty_sections() -> None:
    meta = MeetingMeta(
        slug="2026-06-10_09-00_untitled",
        started_at=datetime(2026, 6, 10, 9, 0, tzinfo=UTC),
        calendar_title="Untitled",
    )
    transcript = TranscriptResult(
        assemblyai_id="tx-123",
        segments=(TranscriptSegment("Speaker A", 1, "Hello."),),
    )

    markdown = render_meeting_markdown(meta, transcript, SummaryResult.skipped())

    assert "_Summarization skipped._" in markdown
    assert markdown.count("_None identified._") == 2
    assert "summary_status: \"skipped\"" in markdown

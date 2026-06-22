"""Tests for meeting markdown rendering."""

from __future__ import annotations

from datetime import UTC, datetime

from meeting_memory.service.markdown import render_notes_markdown, render_transcript_markdown
from meeting_memory.types.meeting import MeetingMeta
from meeting_memory.types.summary import ActionItem, SummaryResult
from meeting_memory.types.transcript import TranscriptResult, TranscriptSegment


def test_render_transcript_markdown_contains_frontmatter_and_transcript_only() -> None:
    markdown = render_transcript_markdown(
        _meta(),
        _transcript(),
        speaker_candidates=("Alex", "Casey"),
    )

    assert markdown.startswith("---\n")
    assert 'id: "2026-06-10_09-00_product-sync"' in markdown
    assert 'participants: ["Speaker A", "Speaker B"]' in markdown
    assert 'speaker_candidates: ["Alex", "Casey"]' in markdown
    assert "speaker_aliases: {}" in markdown
    assert 'speaker_status: "needs_review"' in markdown
    assert "summary_status" not in markdown
    assert "# Transcript" in markdown
    assert "## Summary" not in markdown
    assert "**Speaker A** (0:00:05): We should ship the demo." in markdown


def test_render_transcript_markdown_applies_aliases_by_code() -> None:
    markdown = render_transcript_markdown(
        _meta(),
        _transcript(),
        speaker_aliases={"Speaker A": "Alex"},
        speaker_status="confirmed",
    )

    assert 'participants: ["Alex", "Speaker B"]' in markdown
    assert 'speaker_aliases: {"Speaker A": "Alex"}' in markdown
    assert 'speaker_status: "confirmed"' in markdown
    assert "**Alex** (0:00:05): We should ship the demo." in markdown
    assert "**Speaker B** (0:00:12): I can send notes." in markdown


def test_render_notes_markdown_contains_only_derived_sections() -> None:
    summary = SummaryResult(
        summary="The team agreed to ship the demo.",
        decisions=("Ship the demo",),
        action_items=(ActionItem(owner="Alex", task="Send notes", due_date="Friday"),),
    )

    markdown = render_notes_markdown(_meta(), summary)

    assert "# Meeting Notes" in markdown
    assert "**Source:** transcript.md" in markdown
    assert "## Summary" in markdown
    assert "## Decisions" in markdown
    assert "## Action Items" in markdown
    assert "- [ ] Alex: Send notes (Due: Friday)" in markdown
    assert "**Speaker A**" not in markdown


def test_render_notes_markdown_uses_placeholders_for_empty_sections() -> None:
    markdown = render_notes_markdown(_meta(), SummaryResult.skipped())

    assert "_Summarization skipped._" in markdown
    assert markdown.count("_None identified._") == 2
    assert 'summary_status: "skipped"' in markdown


def _meta() -> MeetingMeta:
    return MeetingMeta(
        slug="2026-06-10_09-00_product-sync",
        started_at=datetime(2026, 6, 10, 9, 0, tzinfo=UTC),
        calendar_title="Product Sync",
        duration_minutes=42,
    )


def _transcript() -> TranscriptResult:
    return TranscriptResult(
        assemblyai_id="tx-123",
        segments=(
            TranscriptSegment("Speaker A", 5, "We should ship the demo."),
            TranscriptSegment("Speaker B", 12, "I can send notes."),
        ),
    )

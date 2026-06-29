"""Tests for optional speaker mapping."""

from __future__ import annotations

from datetime import UTC, datetime

from meeting_memory.service.markdown import render_meeting_markdown
from meeting_memory.service.speaker_mapping import apply_speaker_mapping
from meeting_memory.types.meeting import MeetingMeta
from meeting_memory.types.summary import SummaryResult
from meeting_memory.types.transcript import TranscriptResult, TranscriptSegment


def test_apply_speaker_mapping_replaces_known_labels_and_preserves_unknown() -> None:
    transcript = _transcript()

    mapped = apply_speaker_mapping(transcript, {"Speaker A": "Alex"})

    assert mapped.participants == ("Alex", "Speaker B")
    assert mapped.segments[0].speaker_label == "Alex"
    assert mapped.segments[1].speaker_label == "Speaker B"


def test_render_meeting_markdown_applies_speaker_aliases_to_participants_and_transcript() -> None:
    markdown = render_meeting_markdown(
        MeetingMeta(
            slug="2026-06-10_09-00_product-sync",
            started_at=datetime(2026, 6, 10, 9, 0, tzinfo=UTC),
            calendar_title="Product Sync",
            duration_minutes=12,
        ),
        _transcript(),
        SummaryResult(summary="A short summary."),
        speaker_aliases={"Speaker A": "Alex"},
    )

    assert 'participants: ["Alex", "Speaker B"]' in markdown
    assert "**Alex** (0:00:05): Hello." in markdown
    assert "**Speaker A**" not in markdown


def _transcript() -> TranscriptResult:
    return TranscriptResult(
        assemblyai_id="tx-123",
        segments=(
            TranscriptSegment("Speaker A", 5, "Hello."),
            TranscriptSegment("Speaker B", 12, "Hi."),
        ),
    )

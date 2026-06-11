"""Tests for pure boundary models."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from meeting_memory.types.meeting import MeetingMeta, build_meeting_slug, slugify_title
from meeting_memory.types.summary import ActionItem, SummaryResult
from meeting_memory.types.transcript import TranscriptResult, TranscriptSegment, format_timestamp


def test_meeting_slug_format_and_title_cleanup() -> None:
    started_at = datetime(2026, 6, 10, 9, 0, tzinfo=UTC)

    assert slugify_title("Product Sync: ACME & B2 Launch!!!") == "product-sync-acme-b2-launch"
    assert slugify_title("A" * 80) == "a" * 40
    assert build_meeting_slug(started_at, "Product Sync") == "2026-06-10_09-00_product-sync"


def test_meeting_meta_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="slug"):
        MeetingMeta(slug="", started_at=datetime.now(tz=UTC))

    with pytest.raises(ValueError, match="duration_minutes"):
        MeetingMeta(
            slug="example",
            started_at=datetime.now(tz=UTC),
            duration_minutes=-1,
        )


def test_transcript_preserves_participant_order_and_formats_timestamps() -> None:
    transcript = TranscriptResult(
        assemblyai_id="tx-123",
        segments=(
            TranscriptSegment("Speaker B", 5, "First"),
            TranscriptSegment("Speaker A", 3723.9, "Second"),
            TranscriptSegment("Speaker B", 9, "Third"),
        ),
    )

    assert transcript.participants == ("Speaker B", "Speaker A")
    assert transcript.segments[1].timestamp == "1:02:03"
    assert format_timestamp(65) == "0:01:05"


def test_transcript_requires_segments_unless_error_is_set() -> None:
    with pytest.raises(ValueError, match="segments"):
        TranscriptResult(assemblyai_id="tx-123", segments=())

    failed = TranscriptResult(assemblyai_id="tx-123", segments=(), error="API failed")
    assert failed.error == "API failed"


def test_summary_status_helpers_and_validation() -> None:
    summary = SummaryResult(
        summary="We agreed to ship.",
        decisions=("Ship the demo",),
        action_items=(ActionItem(owner="Alex", task="Send notes", due_date="Friday"),),
    )

    assert summary.status == "ok"
    assert SummaryResult.skipped().status == "skipped"
    assert SummaryResult.failed().status == "failed"

    with pytest.raises(ValueError, match="summary is required"):
        SummaryResult(summary="", status="ok")

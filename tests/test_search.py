"""Tests for local meeting search."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from meeting_memory.service.search import search_meetings
from meeting_memory.service.storage import write_meeting_dir
from meeting_memory.types.meeting import MeetingMeta
from meeting_memory.types.summary import SummaryResult
from meeting_memory.types.transcript import TranscriptResult, TranscriptSegment


def test_search_meetings_returns_typed_results_and_ignores_non_meetings(tmp_path: Path) -> None:
    meetings_dir = tmp_path / "meetings"
    old_files = _write_one(
        meetings_dir,
        slug="2026-06-10_09-00_product-sync",
        minutes=0,
        title="Product Sync",
        transcript_text="We should ship the demo next week.",
    )
    new_files = _write_one(
        meetings_dir,
        slug="2026-06-10_10-00_launch-review",
        minutes=60,
        title="Launch Review",
        transcript_text="The demo launch needs updated customer notes.",
    )
    outsider = meetings_dir / "not-ours"
    outsider.mkdir()
    (outsider / "meeting.md").write_text("demo launch noise", encoding="utf-8")

    results = search_meetings(meetings_dir, "demo")

    assert [result.slug for result in results] == [new_files.meta.slug, old_files.meta.slug]
    assert results[0].title == "Launch Review"
    assert results[0].path == new_files.markdown_path
    assert results[0].started_at == datetime(2026, 6, 10, 10, 0, tzinfo=UTC)
    assert "demo launch" in results[0].excerpt
    assert all("not-ours" not in str(result.path) for result in results)


def test_search_meetings_requires_all_query_terms(tmp_path: Path) -> None:
    meetings_dir = tmp_path / "meetings"
    _write_one(
        meetings_dir,
        slug="2026-06-10_09-00_product-sync",
        minutes=0,
        title="Product Sync",
        transcript_text="The roadmap has launch notes.",
    )
    match = _write_one(
        meetings_dir,
        slug="2026-06-10_10-00_customer-demo",
        minutes=60,
        title="Customer Demo",
        transcript_text="The launch notes mention the customer demo.",
    )

    results = search_meetings(meetings_dir, "customer launch")

    assert [result.slug for result in results] == [match.meta.slug]


def test_search_meetings_returns_empty_for_blank_or_missing_dir(tmp_path: Path) -> None:
    assert search_meetings(tmp_path / "missing", "demo") == []
    assert search_meetings(tmp_path, "   ") == []


def _write_one(
    meetings_dir: Path,
    *,
    slug: str,
    minutes: int,
    title: str,
    transcript_text: str,
):
    audio_source = meetings_dir.parent / f"{slug}.m4a"
    audio_source.write_bytes(b"fake audio")
    started_at = datetime(2026, 6, 10, 9, 0, tzinfo=UTC) + timedelta(minutes=minutes)
    meta = MeetingMeta(
        slug=slug,
        started_at=started_at,
        calendar_title=title,
        duration_minutes=minutes,
    )
    return write_meeting_dir(
        meetings_dir,
        meta,
        audio_source,
        TranscriptResult(
            assemblyai_id=slug,
            segments=(TranscriptSegment("Speaker A", 5, transcript_text),),
        ),
        SummaryResult(summary=f"{title} summary."),
    )

"""Tests for local meeting storage."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from meeting_memory.service.storage import (
    is_ours,
    list_recent_meetings,
    read_frontmatter,
    update_b2_frontmatter,
    write_meeting_dir,
)
from meeting_memory.types.meeting import MeetingMeta
from meeting_memory.types.summary import SummaryResult
from meeting_memory.types.transcript import TranscriptResult, TranscriptSegment


def test_write_meeting_dir_copies_audio_and_avoids_slug_collisions(tmp_path: Path) -> None:
    audio_source = tmp_path / "source.m4a"
    audio_source.write_bytes(b"fake audio")
    meetings_dir = tmp_path / "meetings"
    meta = MeetingMeta(
        slug="2026-06-10_09-00_product-sync",
        started_at=datetime(2026, 6, 10, 9, 0, tzinfo=UTC),
        calendar_title="Product Sync",
        duration_minutes=12,
    )

    first = write_meeting_dir(meetings_dir, meta, audio_source, _transcript("tx-1"), _summary())
    second = write_meeting_dir(meetings_dir, meta, audio_source, _transcript("tx-2"), _summary())

    assert first.meta.slug == "2026-06-10_09-00_product-sync"
    assert second.meta.slug == "2026-06-10_09-00_product-sync-2"
    assert first.audio_path.read_bytes() == b"fake audio"
    assert first.markdown_path.exists()
    assert first.markdown_path.name == "transcript.md"
    assert first.notes_path is not None
    assert first.notes_path.exists()
    assert is_ours(first.directory)

    frontmatter = read_frontmatter(first.markdown_path)
    assert frontmatter["id"] == first.meta.slug
    assert frontmatter["assemblyai_id"] == "tx-1"
    assert frontmatter["b2_status"] == "pending"


def test_update_b2_frontmatter_preserves_markdown_body(tmp_path: Path) -> None:
    stored = _write_one(tmp_path, "2026-06-10_09-00_product-sync", 0)

    update_b2_frontmatter(
        stored.markdown_path,
        b2_audio="meetings/example/recording.m4a",
        b2_transcript="meetings/example/transcript.md",
        b2_status="ok",
    )

    markdown = stored.markdown_path.read_text(encoding="utf-8")
    frontmatter = read_frontmatter(stored.markdown_path)
    assert frontmatter["b2_audio"] == "meetings/example/recording.m4a"
    assert frontmatter["b2_transcript"] == "meetings/example/transcript.md"
    assert frontmatter["b2_status"] == "ok"
    assert "# Transcript" in markdown
    assert "**Speaker A**" in markdown


def test_list_recent_meetings_filters_to_ours_and_limits_results(tmp_path: Path) -> None:
    for index in range(6):
        _write_one(tmp_path, f"2026-06-10_09-0{index}_product-sync", index)
    outsider = tmp_path / "meetings" / "not-ours"
    outsider.mkdir()
    (outsider / "meeting.md").write_text("# Not ours\n", encoding="utf-8")

    recent = list_recent_meetings(tmp_path / "meetings")

    assert len(recent) == 5
    assert recent[0].slug == "2026-06-10_09-05_product-sync"
    assert recent[-1].slug == "2026-06-10_09-01_product-sync"
    assert all("not-ours" not in str(item.directory) for item in recent)


def _write_one(tmp_path: Path, slug: str, minutes: int):
    audio_source = tmp_path / f"{slug}.m4a"
    audio_source.write_bytes(b"fake audio")
    started_at = datetime(2026, 6, 10, 9, 0, tzinfo=UTC) + timedelta(minutes=minutes)
    meta = MeetingMeta(
        slug=slug,
        started_at=started_at,
        calendar_title="Product Sync",
        duration_minutes=minutes,
    )
    return write_meeting_dir(
        tmp_path / "meetings",
        meta,
        audio_source,
        _transcript(slug),
        _summary(),
    )


def _transcript(identifier: str) -> TranscriptResult:
    return TranscriptResult(
        assemblyai_id=identifier,
        segments=(TranscriptSegment("Speaker A", 5, "Hello from the meeting."),),
    )


def _summary() -> SummaryResult:
    return SummaryResult(summary="A short summary.")

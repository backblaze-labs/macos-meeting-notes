"""Tests for B2 resync scanning."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from meeting_memory.service.storage import (
    read_frontmatter,
    update_b2_frontmatter,
    write_meeting_dir,
)
from meeting_memory.service.sync import sync_pending_meetings
from meeting_memory.types.meeting import B2UploadResult, MeetingFiles, MeetingMeta
from meeting_memory.types.summary import SummaryResult
from meeting_memory.types.transcript import TranscriptResult, TranscriptSegment


def test_sync_pending_meetings_uploads_failed_and_pending_entries(tmp_path: Path) -> None:
    meetings_dir = tmp_path / "meetings"
    first = _write_meeting(meetings_dir, "first")
    second = _write_meeting(meetings_dir, "second")
    third = _write_meeting(meetings_dir, "third")
    update_b2_frontmatter(first.markdown_path, b2_status="upload_failed")
    update_b2_frontmatter(third.markdown_path, b2_status="ok")
    b2 = FakeB2()

    result = sync_pending_meetings(meetings_dir, b2)

    assert result.attempted == 2
    assert result.uploaded == 2
    assert result.failed == 0
    assert [files.meta.slug for files in b2.uploaded] == ["first", "second"]
    assert read_frontmatter(first.markdown_path)["b2_status"] == "ok"
    assert read_frontmatter(second.markdown_path)["b2_status"] == "ok"


def test_sync_pending_meetings_marks_failures(tmp_path: Path) -> None:
    meetings_dir = tmp_path / "meetings"
    stored = _write_meeting(meetings_dir, "first")

    result = sync_pending_meetings(meetings_dir, FailingB2())

    assert result.attempted == 1
    assert result.uploaded == 0
    assert result.failed == 1
    assert read_frontmatter(stored.markdown_path)["b2_status"] == "upload_failed"


def test_sync_pending_meetings_uploads_legacy_meeting_markdown(tmp_path: Path) -> None:
    meetings_dir = tmp_path / "meetings"
    stored = _write_meeting(meetings_dir, "legacy")
    legacy_markdown = stored.directory / "meeting.md"
    stored.markdown_path.rename(legacy_markdown)
    update_b2_frontmatter(legacy_markdown, b2_status="upload_failed")
    b2 = FakeB2()

    result = sync_pending_meetings(meetings_dir, b2)

    assert result.uploaded == 1
    assert b2.uploaded[0].markdown_path == legacy_markdown
    assert read_frontmatter(legacy_markdown)["b2_status"] == "ok"


def test_sync_pending_meetings_uploads_recording_parts(tmp_path: Path) -> None:
    meetings_dir = tmp_path / "meetings"
    meeting_dir = meetings_dir / "multipart"
    meeting_dir.mkdir(parents=True)
    (meeting_dir / "recording-part-1_17-00.m4a").write_bytes(b"one")
    (meeting_dir / "recording-part-2_17-03.m4a").write_bytes(b"two")
    (meeting_dir / "transcript.md").write_text(
        "\n".join(
            [
                "---",
                'id: "multipart"',
                'date: "2026-06-22T17:00:00+00:00"',
                "duration_minutes: 2",
                'calendar_title: "Multipart"',
                'b2_status: "upload_failed"',
                "---",
                "# Transcript",
                "",
            ]
        ),
        encoding="utf-8",
    )
    b2 = FakeB2()

    result = sync_pending_meetings(meetings_dir, b2)

    assert result.uploaded == 1
    assert b2.uploaded[0].audio_path.name == "recording-part-1_17-00.m4a"
    assert [path.name for path in b2.uploaded[0].extra_audio_paths] == [
        "recording-part-2_17-03.m4a"
    ]


class FakeB2:
    def __init__(self):
        self.uploaded: list[MeetingFiles] = []

    def upload_meeting(self, files: MeetingFiles) -> B2UploadResult:
        self.uploaded.append(files)
        return B2UploadResult(
            audio_key=f"meetings/{files.meta.slug}/recording.m4a",
            transcript_key=f"meetings/{files.meta.slug}/transcript.md",
        )


class FailingB2:
    def upload_meeting(self, files: MeetingFiles) -> B2UploadResult:
        raise RuntimeError("nope")


def _write_meeting(meetings_dir: Path, slug: str) -> MeetingFiles:
    audio = meetings_dir.parent / f"{slug}.m4a"
    audio.write_bytes(b"audio")
    return write_meeting_dir(
        meetings_dir,
        MeetingMeta(slug=slug, started_at=datetime(2026, 6, 11, 9, 0, tzinfo=UTC)),
        audio,
        TranscriptResult(
            assemblyai_id=f"tx-{slug}",
            segments=(TranscriptSegment("Speaker A", 1, "Hello."),),
        ),
        SummaryResult(summary="Summary."),
    )

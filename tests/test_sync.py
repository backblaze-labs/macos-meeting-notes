"""Tests for B2 resync scanning."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from meeting_memory.service import legacy_snapshot
from meeting_memory.service.frontmatter import replace_frontmatter, split_frontmatter
from meeting_memory.service.meeting_store import MeetingStore
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
    v2 = MeetingStore(meetings_dir).commit(
        first.audio_path,
        MeetingMeta(
            slug="2026-06-11_12-00_v2",
            started_at=datetime(2026, 6, 11, 12, tzinfo=UTC),
        ),
    )
    text = v2.transcript_path.read_text(encoding="utf-8")
    frontmatter, _ = split_frontmatter(text)
    frontmatter["b2_status"] = "upload_failed"
    v2.transcript_path.write_text(
        replace_frontmatter(text, frontmatter),
        encoding="utf-8",
    )
    b2 = FakeB2()

    result = sync_pending_meetings(meetings_dir, b2)

    assert result.attempted == 2
    assert result.uploaded == 2
    assert result.failed == 0
    assert [request.meeting_slug for request in b2.uploaded] == ["first", "second"]
    assert read_frontmatter(first.markdown_path)["b2_status"] == "ok"
    assert read_frontmatter(second.markdown_path)["b2_status"] == "ok"
    assert read_frontmatter(v2.transcript_path)["b2_status"] == "upload_failed"


def test_sync_pending_meetings_marks_failures(tmp_path: Path) -> None:
    meetings_dir = tmp_path / "meetings"
    stored = _write_meeting(meetings_dir, "first")

    result = sync_pending_meetings(meetings_dir, FailingB2())

    assert result.attempted == 1
    assert result.uploaded == 0
    assert result.failed == 1
    assert read_frontmatter(stored.markdown_path)["b2_status"] == "upload_failed"


def test_sync_failure_preserves_existing_remote_keys(tmp_path: Path) -> None:
    meetings_dir = tmp_path / "meetings"
    stored = _write_meeting(meetings_dir, "first")
    update_b2_frontmatter(
        stored.markdown_path,
        b2_status="upload_failed",
        b2_audio="meetings/first/recording.m4a",
        b2_transcript="meetings/first/transcript.md",
    )

    result = sync_pending_meetings(meetings_dir, FailingB2())

    frontmatter = read_frontmatter(stored.markdown_path)
    assert result.failed == 1
    assert frontmatter["b2_audio"] == "meetings/first/recording.m4a"
    assert frontmatter["b2_transcript"] == "meetings/first/transcript.md"


def test_sync_pending_meetings_uploads_legacy_meeting_markdown(tmp_path: Path) -> None:
    meetings_dir = tmp_path / "meetings"
    stored = _write_meeting(meetings_dir, "legacy")
    legacy_markdown = stored.directory / "meeting.md"
    stored.markdown_path.rename(legacy_markdown)
    update_b2_frontmatter(legacy_markdown, b2_status="upload_failed")
    b2 = FakeB2()

    result = sync_pending_meetings(meetings_dir, b2)

    assert result.uploaded == 1
    assert b2.uploaded[0].transcript.filename == "meeting.md"
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
    assert b2.uploaded[0].audio[0].filename == "recording-part-1_17-00.m4a"
    assert [item.filename for item in b2.uploaded[0].audio[1:]] == [
        "recording-part-2_17-03.m4a"
    ]


def test_legacy_sync_path_swap_never_uploads_or_mutates_v2_bytes(tmp_path: Path) -> None:
    meetings = tmp_path / "meetings"
    legacy = _write_meeting(meetings, "aaa-legacy")
    update_b2_frontmatter(legacy.transcript_path, b2_status="upload_failed")
    v2 = MeetingStore(meetings).commit(
        legacy.audio_path,
        MeetingMeta("zzz-v2", datetime(2026, 6, 11, 12, tzinfo=UTC)),
    )
    v2_before = v2.transcript_path.read_bytes()

    class SwappingB2(FakeB2):
        def upload_legacy_snapshot(self, request):
            assert request.audio[0].stream.read() == b"audio"
            assert b"aaa-legacy" in request.transcript.stream.read()
            legacy.transcript_path.rename(legacy.transcript_path.with_suffix(".original"))
            legacy.transcript_path.symlink_to(v2.transcript_path)
            return super().upload_legacy_snapshot(request)

    result = sync_pending_meetings(meetings, SwappingB2())

    assert result == type(result)(attempted=1, uploaded=0, failed=1)
    assert v2.transcript_path.read_bytes() == v2_before


def test_legacy_slug_and_uploaded_transcript_come_from_one_snapshot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    meetings = tmp_path / "meetings"
    legacy = _write_meeting(meetings, "legacy")
    update_b2_frontmatter(legacy.transcript_path, b2_status="upload_failed")
    original_text = legacy.transcript_path.read_text(encoding="utf-8")
    original_copy = legacy_snapshot.private_stable_copy
    copies = 0

    def mutate_after_copy(descriptor):
        nonlocal copies
        reader = original_copy(descriptor)
        copies += 1
        if copies == 1:
            legacy.transcript_path.write_text(
                original_text.replace('id: "legacy"', 'id: "different"'),
                encoding="utf-8",
            )
        return reader

    class CapturingB2:
        def __init__(self) -> None:
            self.slug = ""
            self.transcript = b""

        def upload_legacy_snapshot(self, request):
            self.slug = request.meeting_slug
            self.transcript = request.transcript.stream.read()
            return B2UploadResult("audio-key", "transcript-key")

    monkeypatch.setattr(legacy_snapshot, "private_stable_copy", mutate_after_copy)
    b2 = CapturingB2()

    result = sync_pending_meetings(meetings, b2)

    assert result == type(result)(attempted=1, uploaded=0, failed=1)
    assert b2.slug == "legacy"
    assert b'id: "legacy"' in b2.transcript
    assert b'id: "different"' not in b2.transcript


class FakeB2:
    def __init__(self):
        self.uploaded = []

    def upload_legacy_snapshot(self, request) -> B2UploadResult:
        assert all(not item.stream.writable() for item in request.audio)
        assert not request.transcript.stream.writable()
        self.uploaded.append(request)
        return B2UploadResult(
            audio_key=f"meetings/{request.meeting_slug}/{request.audio[0].filename}",
            transcript_key=f"meetings/{request.meeting_slug}/transcript.md",
        )


class FailingB2:
    def upload_legacy_snapshot(self, request) -> B2UploadResult:
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

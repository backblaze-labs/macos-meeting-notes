"""Tests for retrying failed meeting processing."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from meeting_memory.service.frontmatter import replace_frontmatter, split_frontmatter
from meeting_memory.service.meeting_store import MeetingStore
from meeting_memory.service.processing_retry import (
    retry_failed_processing,
    should_retry_processing,
)
from meeting_memory.service.storage import write_meeting_dir
from meeting_memory.types.egress import EgressPaused
from meeting_memory.types.meeting import MeetingMeta, PostCommitPolicy
from meeting_memory.types.summary import SummaryResult
from meeting_memory.types.transcript import TranscriptResult, TranscriptSegment


def test_should_retry_processing_detects_transcription_failures() -> None:
    assert should_retry_processing({"assemblyai_id": "transcription-failed"})
    assert not should_retry_processing({"summary_status": "failed"})
    assert not should_retry_processing({"assemblyai_id": "ok", "summary_status": "ok"})


def test_retry_failed_processing_processes_existing_meeting_dirs(tmp_path: Path) -> None:
    meetings_dir = tmp_path / "meetings"
    audio = tmp_path / "recording.m4a"
    audio.write_bytes(b"audio")
    failed = write_meeting_dir(
        meetings_dir,
        MeetingMeta(
            slug="2026-06-11_09-00_failed",
            started_at=datetime(2026, 6, 11, 9, 0, tzinfo=UTC),
            calendar_title="Failed",
        ),
        audio,
        TranscriptResult("transcription-failed", (), error="offline"),
        SummaryResult.failed(),
    )
    write_meeting_dir(
        meetings_dir,
        MeetingMeta(
            slug="2026-06-11_10-00_ok",
            started_at=datetime(2026, 6, 11, 10, 0, tzinfo=UTC),
            calendar_title="OK",
        ),
        audio,
        TranscriptResult(
            "ok",
            (TranscriptSegment("Speaker A", 0, "hello"),),
        ),
        SummaryResult("Summary"),
    )
    v2 = MeetingStore(meetings_dir).commit(
        audio,
        MeetingMeta(
            slug="2026-06-11_11-00_v2",
            started_at=datetime(2026, 6, 11, 11, tzinfo=UTC),
        ),
        PostCommitPolicy(transcription=True),
    )
    text = v2.transcript_path.read_text(encoding="utf-8")
    frontmatter, _ = split_frontmatter(text)
    frontmatter["assemblyai_id"] = "transcription-failed"
    v2.transcript_path.write_text(
        replace_frontmatter(text, frontmatter),
        encoding="utf-8",
    )
    processor = FakeProcessor()

    result = retry_failed_processing(meetings_dir, processor)

    assert result.attempted == 1
    assert result.completed == 1
    assert result.failed == 0
    assert processor.audio == [b"audio"]
    updated, body = split_frontmatter(failed.transcript_path.read_text(encoding="utf-8"))
    assert updated["assemblyai_id"] == "retry-ok"
    assert "Recovered" in body


def test_paused_legacy_transcription_preserves_retryable_metadata(tmp_path: Path) -> None:
    meetings = tmp_path / "meetings"
    audio = tmp_path / "recording.m4a"
    audio.write_bytes(b"audio")
    failed = write_meeting_dir(
        meetings,
        MeetingMeta("paused", datetime(2026, 6, 11, 9, tzinfo=UTC)),
        audio,
        TranscriptResult("transcription-failed", (), error="offline"),
        SummaryResult.failed(),
    )
    before = failed.transcript_path.read_bytes()

    class Paused:
        def transcribe(self, _audio):
            raise EgressPaused("paused")

    result = retry_failed_processing(meetings, Paused())

    assert result.failed == result.completed == 0
    assert failed.transcript_path.read_bytes() == before


def test_legacy_transcription_path_swap_never_reads_or_mutates_v2(tmp_path: Path) -> None:
    meetings = tmp_path / "meetings"
    audio = tmp_path / "recording.m4a"
    audio.write_bytes(b"legacy audio")
    legacy = write_meeting_dir(
        meetings,
        MeetingMeta("aaa-legacy", datetime(2026, 6, 11, 9, tzinfo=UTC)),
        audio,
        TranscriptResult("transcription-failed", (), error="offline"),
        SummaryResult.failed(),
    )
    v2 = MeetingStore(meetings).commit(
        audio,
        MeetingMeta("zzz-v2", datetime(2026, 6, 11, 10, tzinfo=UTC)),
    )
    v2_before = v2.transcript_path.read_bytes()

    class SwappingTranscriber:
        def transcribe(self, stream):
            assert stream.read() == b"legacy audio"
            legacy.transcript_path.rename(legacy.transcript_path.with_suffix(".original"))
            legacy.transcript_path.symlink_to(v2.transcript_path)
            return TranscriptResult(
                "retry-ok",
                (TranscriptSegment("A", 0, "Private"),),
            )

    result = retry_failed_processing(meetings, SwappingTranscriber())

    assert result == type(result)(attempted=1, completed=0, failed=1)
    assert v2.transcript_path.read_bytes() == v2_before


def test_retry_stops_before_next_provider_call_after_disable(tmp_path: Path) -> None:
    meetings = tmp_path / "meetings"
    audio = tmp_path / "recording.m4a"
    audio.write_bytes(b"audio")
    for slug in ("first", "second"):
        write_meeting_dir(
            meetings,
            MeetingMeta(slug, datetime(2026, 6, 11, 9, tzinfo=UTC)),
            audio,
            TranscriptResult("transcription-failed", (), error="offline"),
            SummaryResult.failed(),
        )
    enabled = True
    processor = FakeProcessor()

    def capability_enabled() -> bool:
        nonlocal enabled
        if processor.audio:
            enabled = False
        return enabled

    result = retry_failed_processing(
        meetings,
        processor,
        enabled=capability_enabled,
    )

    assert result.attempted == 1
    assert processor.audio == [b"audio"]


class FakeProcessor:
    def __init__(self):
        self.audio: list[bytes] = []

    def transcribe(self, audio) -> TranscriptResult:
        self.audio.append(audio.read())
        return TranscriptResult(
            "retry-ok",
            (TranscriptSegment("Speaker A", 0, "Recovered"),),
        )

"""Tests for retrying failed meeting processing."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from meeting_memory.service.processing_retry import (
    retry_failed_processing,
    should_retry_processing,
)
from meeting_memory.service.storage import write_meeting_dir
from meeting_memory.types.meeting import MeetingFiles, MeetingMeta
from meeting_memory.types.summary import SummaryResult
from meeting_memory.types.transcript import TranscriptResult, TranscriptSegment


def test_should_retry_processing_detects_transcription_or_summary_failures() -> None:
    assert should_retry_processing({"assemblyai_id": "transcription-failed"})
    assert should_retry_processing({"summary_status": "failed"})
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
    processor = FakeProcessor()

    result = retry_failed_processing(meetings_dir, processor)

    assert result.attempted == 1
    assert result.completed == 1
    assert result.failed == 0
    assert processor.files == [failed]


class FakeProcessor:
    def __init__(self):
        self.files: list[MeetingFiles] = []

    def process_files(self, files: MeetingFiles) -> None:
        self.files.append(files)

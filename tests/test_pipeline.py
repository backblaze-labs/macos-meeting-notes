"""Tests for fake-client pipeline orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from meeting_memory.service.pipeline import Pipeline
from meeting_memory.service.storage import read_frontmatter
from meeting_memory.types.events import NotifyEvent
from meeting_memory.types.meeting import B2UploadResult, MeetingFiles, MeetingMeta
from meeting_memory.types.summary import SummaryResult
from meeting_memory.types.transcript import TranscriptResult, TranscriptSegment


def test_pipeline_happy_path_writes_files_emits_event_and_updates_b2(tmp_path: Path) -> None:
    events: list[NotifyEvent] = []
    transcriber = FakeTranscriber(_transcript("tx-123"))
    summarizer = FakeSummarizer(SummaryResult(summary="The meeting was productive."))
    b2 = FakeB2(events)
    pipeline = Pipeline(
        meetings_dir=tmp_path / "meetings",
        transcription_client=transcriber,
        summarizer_client=summarizer,
        b2_client=b2,
        event_sink=events.append,
    )

    result = pipeline.run(_audio_source(tmp_path), _meta())

    assert result.b2_uploaded is True
    assert result.b2_error is None
    assert result.files.audio_path.read_bytes() == b"fake audio"
    assert result.files.markdown_path.exists()
    assert transcriber.audio_path == result.files.audio_path
    assert summarizer.transcript_text is None
    assert b2.files == result.files
    assert b2.event_count_at_upload == 1

    assert events == [
        NotifyEvent(
            title="Meeting ready",
            body="Product Sync · transcript ready · review speakers",
            action_label="Review Speakers",
            action="review_speakers",
            meeting_directory=result.files.directory,
        )
    ]

    frontmatter = read_frontmatter(result.files.markdown_path)
    assert frontmatter["assemblyai_id"] == "tx-123"
    assert frontmatter["speaker_status"] == "needs_review"
    assert frontmatter["b2_audio"] == f"meetings/{result.files.meta.slug}/recording.m4a"
    assert frontmatter["b2_transcript"] == f"meetings/{result.files.meta.slug}/transcript.md"
    assert frontmatter["b2_status"] == "ok"


def test_pipeline_does_not_summarize_after_recording_stop(tmp_path: Path) -> None:
    events: list[NotifyEvent] = []
    pipeline = Pipeline(
        meetings_dir=tmp_path / "meetings",
        transcription_client=FakeTranscriber(_transcript("tx-123")),
        summarizer_client=FailingSummarizer(),
        event_sink=events.append,
    )

    result = pipeline.run(_audio_source(tmp_path), _meta())
    markdown = result.files.markdown_path.read_text(encoding="utf-8")
    frontmatter = read_frontmatter(result.files.markdown_path)

    assert result.summary.status == "skipped"
    assert result.b2_uploaded is False
    assert events[0].body == "Product Sync · transcript ready · review speakers"
    assert frontmatter["speaker_status"] == "needs_review"
    assert frontmatter["b2_status"] == "pending"
    assert "## Summary" not in markdown
    assert "**Speaker A** (0:00:05): Hello from the meeting." in markdown


def test_pipeline_transcription_failure_writes_non_empty_meeting_md(tmp_path: Path) -> None:
    events: list[NotifyEvent] = []
    summarizer = FakeSummarizer(SummaryResult(summary="Should not be used."))
    pipeline = Pipeline(
        meetings_dir=tmp_path / "meetings",
        transcription_client=FailingTranscriber(),
        summarizer_client=summarizer,
        event_sink=events.append,
    )

    result = pipeline.run(_audio_source(tmp_path), _meta())
    markdown = result.files.markdown_path.read_text(encoding="utf-8")
    frontmatter = read_frontmatter(result.files.markdown_path)

    assert result.transcript.error == "transcription unavailable"
    assert result.summary.status == "skipped"
    assert summarizer.transcript_text is None
    assert result.files.audio_path.exists()
    assert result.files.markdown_path.stat().st_size > 0
    assert frontmatter["assemblyai_id"] == "transcription-failed"
    assert "_Transcription failed: transcription unavailable_" in markdown
    assert events[0].body == "Product Sync · transcription failed. Audio saved locally."


def test_pipeline_marks_frontmatter_when_b2_upload_fails(tmp_path: Path) -> None:
    events: list[NotifyEvent] = []
    pipeline = Pipeline(
        meetings_dir=tmp_path / "meetings",
        transcription_client=FakeTranscriber(_transcript("tx-123")),
        summarizer_client=FakeSummarizer(SummaryResult(summary="A summary.")),
        b2_client=FailingB2(),
        event_sink=events.append,
    )

    result = pipeline.run(_audio_source(tmp_path), _meta())
    frontmatter = read_frontmatter(result.files.markdown_path)

    assert result.b2_uploaded is False
    assert result.b2_error == "b2 unavailable"
    assert events[0].title == "Meeting ready"
    assert frontmatter["b2_audio"] is None
    assert frontmatter["b2_transcript"] is None
    assert frontmatter["b2_status"] == "upload_failed"


def test_pipeline_applies_speaker_mapping_when_rendering_markdown(tmp_path: Path) -> None:
    summarizer = FakeSummarizer(SummaryResult(summary="A summary."))
    pipeline = Pipeline(
        meetings_dir=tmp_path / "meetings",
        transcription_client=FakeTranscriber(_transcript("tx-123")),
        summarizer_client=summarizer,
        speaker_mapping={"Speaker A": "Alex"},
    )

    result = pipeline.run(_audio_source(tmp_path), _meta())
    markdown = result.files.markdown_path.read_text(encoding="utf-8")
    frontmatter = read_frontmatter(result.files.markdown_path)

    assert summarizer.transcript_text is None
    assert frontmatter["participants"] == ["Alex"]
    assert "**Alex** (0:00:05): Hello from the meeting." in markdown


@dataclass
class FakeTranscriber:
    result: TranscriptResult
    audio_path: Path | None = None

    def transcribe(self, audio_path: Path) -> TranscriptResult:
        self.audio_path = audio_path
        return self.result


class FailingTranscriber:
    def transcribe(self, audio_path: Path) -> TranscriptResult:
        raise RuntimeError("transcription unavailable")


@dataclass
class FakeSummarizer:
    result: SummaryResult
    transcript_text: str | None = None

    def summarize(self, transcript_text: str) -> SummaryResult:
        self.transcript_text = transcript_text
        return self.result


class FailingSummarizer:
    def summarize(self, transcript_text: str) -> SummaryResult:
        raise RuntimeError("summarizer unavailable")


@dataclass
class FakeB2:
    events: list[NotifyEvent]
    files: MeetingFiles | None = None
    event_count_at_upload: int | None = None

    def upload_meeting(self, files: MeetingFiles) -> B2UploadResult:
        self.files = files
        self.event_count_at_upload = len(self.events)
        return B2UploadResult(
            audio_key=f"meetings/{files.meta.slug}/recording.m4a",
            transcript_key=f"meetings/{files.meta.slug}/transcript.md",
        )


class FailingB2:
    def upload_meeting(self, files: MeetingFiles) -> B2UploadResult:
        raise RuntimeError("b2 unavailable")


def _audio_source(tmp_path: Path) -> Path:
    path = tmp_path / "recording.m4a"
    path.write_bytes(b"fake audio")
    return path


def _meta() -> MeetingMeta:
    return MeetingMeta(
        slug="2026-06-10_09-00_product-sync",
        started_at=datetime(2026, 6, 10, 9, 0, tzinfo=UTC),
        calendar_title="Product Sync",
        duration_minutes=15,
    )


def _transcript(identifier: str) -> TranscriptResult:
    return TranscriptResult(
        assemblyai_id=identifier,
        segments=(TranscriptSegment("Speaker A", 5, "Hello from the meeting."),),
    )

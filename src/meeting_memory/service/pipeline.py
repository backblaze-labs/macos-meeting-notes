"""Post-recording pipeline orchestration with typed client boundaries."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from meeting_memory.service.storage import (
    create_meeting_dir,
    update_b2_frontmatter,
    write_meeting_markdown,
)
from meeting_memory.types.events import NotifyEvent
from meeting_memory.types.meeting import B2UploadResult, MeetingFiles, MeetingMeta
from meeting_memory.types.summary import SummaryResult
from meeting_memory.types.transcript import TranscriptResult


class TranscriptionClient(Protocol):
    def transcribe(self, audio_path: Path) -> TranscriptResult:
        """Transcribe the copied recording."""


class SummarizerClient(Protocol):
    def summarize(self, transcript_text: str) -> SummaryResult:
        """Summarize transcript text into structured sections."""


class B2Client(Protocol):
    def upload_meeting(self, files: MeetingFiles) -> B2UploadResult:
        """Upload local meeting artifacts and return object keys."""


EventSink = Callable[[NotifyEvent], None]
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class PipelineResult:
    files: MeetingFiles
    transcript: TranscriptResult
    summary: SummaryResult
    b2_uploaded: bool = False
    b2_error: str | None = None


@dataclass(frozen=True)
class Pipeline:
    meetings_dir: Path
    transcription_client: TranscriptionClient
    summarizer_client: SummarizerClient | None = None
    b2_client: B2Client | None = None
    event_sink: EventSink | None = None

    def run(self, audio_source: Path, meta: MeetingMeta) -> PipelineResult:
        files = create_meeting_dir(self.meetings_dir, meta, audio_source)
        transcript = self._transcribe(files.audio_path)
        summary = self._summarize(transcript)

        write_meeting_markdown(files, transcript, summary)
        self._emit_completion(files, transcript, summary)

        b2_uploaded, b2_error = self._upload_to_b2(files)
        return PipelineResult(
            files=files,
            transcript=transcript,
            summary=summary,
            b2_uploaded=b2_uploaded,
            b2_error=b2_error,
        )

    def _transcribe(self, audio_path: Path) -> TranscriptResult:
        try:
            return self.transcription_client.transcribe(audio_path)
        except Exception as exc:
            return TranscriptResult(
                assemblyai_id="transcription-failed",
                segments=(),
                error=str(exc),
            )

    def _summarize(self, transcript: TranscriptResult) -> SummaryResult:
        if transcript.error:
            return SummaryResult.failed()
        if self.summarizer_client is None:
            return SummaryResult.skipped()

        try:
            return self.summarizer_client.summarize(transcript.text)
        except Exception:
            LOGGER.exception("Summarization failed")
            return SummaryResult.failed()

    def _emit_completion(
        self,
        files: MeetingFiles,
        transcript: TranscriptResult,
        summary: SummaryResult,
    ) -> None:
        if self.event_sink is None:
            return

        if transcript.error:
            body = f"{files.meta.calendar_title} · transcription failed. Audio saved locally."
        elif summary.status == "failed":
            body = (
                f"{files.meta.calendar_title} · {files.meta.duration_minutes} min · summary failed"
            )
        elif summary.status == "skipped":
            body = (
                f"{files.meta.calendar_title} · {files.meta.duration_minutes} min · summary skipped"
            )
        else:
            body = f"{files.meta.calendar_title} · {files.meta.duration_minutes} min · ready"
        self.event_sink(
            NotifyEvent(
                title="Meeting ready",
                body=body,
                action_label="Open",
                meeting_directory=files.directory,
            )
        )

    def _upload_to_b2(self, files: MeetingFiles) -> tuple[bool, str | None]:
        if self.b2_client is None:
            return False, None

        try:
            result = self.b2_client.upload_meeting(files)
        except Exception as exc:
            update_b2_frontmatter(files.markdown_path, b2_status="upload_failed")
            return False, str(exc)

        update_b2_frontmatter(
            files.markdown_path,
            b2_audio=result.audio_key,
            b2_transcript=result.transcript_key,
            b2_status="ok",
        )
        return True, None

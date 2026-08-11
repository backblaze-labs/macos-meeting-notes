"""Retry failed local processing using meeting frontmatter as durable state."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol

from meeting_memory.service.legacy_snapshot import (
    capture_legacy_snapshot,
    replace_legacy_metadata,
)
from meeting_memory.service.markdown import render_transcript_markdown
from meeting_memory.types.egress import EgressPaused
from meeting_memory.types.transcript import TranscriptResult


class MeetingProcessor(Protocol):
    def transcribe(self, audio: BinaryIO) -> TranscriptResult:
        """Transcribe one private legacy audio snapshot."""


@dataclass(frozen=True)
class ProcessingRetryResult:
    attempted: int = 0
    completed: int = 0
    failed: int = 0


def retry_failed_processing(
    meetings_dir: Path,
    processor: MeetingProcessor,
    *,
    enabled: Callable[[], bool] = lambda: True,
) -> ProcessingRetryResult:
    if not meetings_dir.exists():
        return ProcessingRetryResult()

    attempted = completed = failed = 0
    for meeting_dir in sorted(path for path in meetings_dir.iterdir() if path.is_dir()):
        if not enabled():
            break
        try:
            manager = capture_legacy_snapshot(meeting_dir)
            snapshot = manager.__enter__()
        except (OSError, TypeError, UnicodeError, ValueError):
            continue
        try:
            if not should_retry_processing(snapshot.frontmatter):
                continue
            if not enabled():
                break
            attempted += 1
            try:
                transcript = processor.transcribe(snapshot.audio[0].stream)
            except EgressPaused:
                return ProcessingRetryResult(
                    attempted=attempted,
                    completed=completed,
                    failed=failed,
                )
            except Exception:
                transcript = TranscriptResult(
                    "transcription-failed",
                    (),
                    error="Provider request failed.",
                )
            replace_legacy_metadata(
                snapshot,
                render_transcript_markdown(
                    snapshot.meta,
                    transcript,
                    speaker_candidates=snapshot.meta.speaker_candidates,
                    b2_audio=_optional_text(snapshot.frontmatter.get("b2_audio")),
                    b2_transcript=_optional_text(snapshot.frontmatter.get("b2_transcript")),
                    b2_status=str(snapshot.frontmatter.get("b2_status") or "pending"),
                ),
            )
        except Exception:
            failed += 1
        else:
            completed += 1
        finally:
            manager.__exit__(None, None, None)
    return ProcessingRetryResult(attempted=attempted, completed=completed, failed=failed)


def should_retry_processing(frontmatter: dict[str, object]) -> bool:
    return frontmatter.get("assemblyai_id") == "transcription-failed"


def _optional_text(value: object) -> str | None:
    text = value.strip() if isinstance(value, str) else ""
    return text or None

"""Retry failed local processing using meeting frontmatter as durable state."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import BinaryIO, Protocol

from meeting_memory.service.legacy_snapshot import (
    capture_legacy_snapshot,
)
from meeting_memory.service.legacy_transcription import (
    claim_legacy_attempt,
    defer_legacy_attempt,
    finish_legacy_attempt,
    record_legacy_provider_id,
)
from meeting_memory.service.markdown import render_transcript_markdown
from meeting_memory.types.egress import EgressPaused
from meeting_memory.types.events import TranscriptionFailed, TranscriptionProgress, TranscriptReady
from meeting_memory.types.local_transcription import (
    LocalModelsUnavailable,
    LocalTranscriptionCancelled,
    LocalTranscriptionError,
)
from meeting_memory.types.meeting import MeetingRef
from meeting_memory.types.transcript import TranscriptResult
from meeting_memory.types.transcription import TranscriptionProvider


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
    event_sink: Callable[[object], None] | None = None,
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
            provider = getattr(processor, "provider", TranscriptionProvider.ASSEMBLYAI)
            split_cloud = provider is TranscriptionProvider.ASSEMBLYAI and (
                callable(getattr(processor, "submit", None))
                and callable(getattr(processor, "resume", None))
            )
            resume_id = _legacy_resume_id(snapshot.frontmatter) if split_cloud else None
            snapshot, identities, attempt_id = claim_legacy_attempt(
                snapshot, provider, resume_id=resume_id
            )
            ref = MeetingRef(snapshot.meta.slug, snapshot.meta.calendar_title, snapshot.directory)
            try:
                if provider is TranscriptionProvider.LOCAL:
                    transcript = processor.transcribe(
                        snapshot.audio[0].stream,
                        progress=lambda progress: (
                            event_sink(TranscriptionProgress(ref, progress)) if event_sink else None
                        ),
                    )
                elif split_cloud:
                    if resume_id is None:
                        resume_id = processor.submit(snapshot.audio[0].stream)
                        snapshot = record_legacy_provider_id(snapshot, identities, resume_id)
                    transcript = processor.resume(resume_id)
                else:
                    transcript = processor.transcribe(snapshot.audio[0].stream)
                if transcript.provider is not provider:
                    raise ValueError("Transcription result belongs to another provider")
                transcript = replace(transcript, attempt_id=attempt_id)
                if transcript.error:
                    raise ValueError("Transcription did not complete")
            except (EgressPaused, LocalModelsUnavailable, LocalTranscriptionCancelled) as exc:
                if event_sink and isinstance(exc, LocalTranscriptionError):
                    event_sink(TranscriptionFailed(ref, str(exc), exc.action))
                defer_legacy_attempt(snapshot, identities, state="pending")
                return ProcessingRetryResult(
                    attempted=attempted,
                    completed=completed,
                    failed=failed,
                )
            except Exception as exc:
                if event_sink:
                    event_sink(
                        TranscriptionFailed(ref, str(exc), exc.action)
                        if isinstance(exc, LocalTranscriptionError)
                        else TranscriptionFailed(ref)
                    )
                defer_legacy_attempt(snapshot, identities, state="failed")
                failed += 1
                continue
            finish_legacy_attempt(
                snapshot,
                identities,
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
            if event_sink:
                event_sink(TranscriptReady(ref))
        finally:
            manager.__exit__(None, None, None)
    return ProcessingRetryResult(attempted=attempted, completed=completed, failed=failed)


def should_retry_processing(frontmatter: dict[str, object]) -> bool:
    if frontmatter.get("transcription_provider") in {"local", "assemblyai"}:
        return frontmatter.get("transcription_status") in {"pending", "running", "failed"}
    return frontmatter.get("assemblyai_id") == "transcription-failed"


def _optional_text(value: object) -> str | None:
    text = value.strip() if isinstance(value, str) else ""
    return text or None


def _legacy_resume_id(frontmatter):
    identifier = frontmatter.get("assemblyai_id")
    if (
        frontmatter.get("transcription_provider") == "assemblyai"
        and frontmatter.get("transcription_attempt_id")
        and isinstance(identifier, str)
        and identifier.strip()
        and identifier != "transcription-failed"
    ):
        return identifier.strip()
    return None

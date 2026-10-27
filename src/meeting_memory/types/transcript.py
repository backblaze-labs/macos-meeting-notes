"""Transcript boundary models."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from meeting_memory.types.speakers import SpeakerUtterance
from meeting_memory.types.transcription import TranscriptionProvider


@dataclass(frozen=True)
class TranscriptSegment:
    speaker_label: str
    start_seconds: float
    text: str

    def __post_init__(self) -> None:
        if not self.speaker_label.strip():
            raise ValueError("speaker_label must not be blank")
        if not math.isfinite(self.start_seconds) or self.start_seconds < 0:
            raise ValueError("start_seconds must be >= 0")
        if not self.text.strip():
            raise ValueError("text must not be blank")

    @property
    def timestamp(self) -> str:
        return format_timestamp(self.start_seconds)


@dataclass(frozen=True)
class TranscriptResult:
    assemblyai_id: str | None = None
    segments: tuple[TranscriptSegment, ...] = ()
    error: str | None = None
    provider: TranscriptionProvider | None = None
    attempt_id: str | None = None

    def __post_init__(self) -> None:
        provider = self.provider or (
            TranscriptionProvider.ASSEMBLYAI
            if self.assemblyai_id is not None
            else TranscriptionProvider.LOCAL
        )
        if not isinstance(provider, TranscriptionProvider):
            raise ValueError("transcript provider must be typed")
        object.__setattr__(self, "provider", provider)
        if provider is TranscriptionProvider.LOCAL and self.assemblyai_id is not None:
            raise ValueError("a local transcript cannot have an AssemblyAI ID")
        if provider is TranscriptionProvider.ASSEMBLYAI and (
            not isinstance(self.assemblyai_id, str) or not self.assemblyai_id.strip()
        ):
            raise ValueError("AssemblyAI transcripts require a non-blank provider ID")
        if self.attempt_id is not None and re.fullmatch(r"[0-9a-f]{32}", self.attempt_id) is None:
            raise ValueError("transcript attempt must be an opaque identifier")
        if not self.segments and not self.error:
            raise ValueError("segments are required unless error is set")

    @property
    def participants(self) -> tuple[str, ...]:
        seen: dict[str, None] = {}
        for segment in self.segments:
            seen.setdefault(segment.speaker_label, None)
        return tuple(seen)

    @property
    def text(self) -> str:
        return "\n".join(segment.text for segment in self.segments)


@dataclass(frozen=True)
class SpeakerReviewState:
    meeting_directory: Path
    transcript_path: Path
    speaker_labels: tuple[str, ...]
    speaker_candidates: tuple[str, ...]
    speaker_aliases: dict[str, str]
    speaker_status: str
    speaker_longest_lines: dict[str, str]
    assemblyai_id: str | None = None
    speaker_suggestions: dict[str, str] = field(default_factory=dict)
    suggestion_message: str = ""
    speaker_evidence: dict[str, str] = field(default_factory=dict)
    speaker_utterances: tuple[SpeakerUtterance, ...] = ()
    transcription_provider: str | None = None
    transcription_attempt_id: str | None = None


def format_timestamp(seconds: float) -> str:
    whole_seconds = int(seconds)
    hours, remainder = divmod(whole_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"

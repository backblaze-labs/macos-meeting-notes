"""Transcript boundary models."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TranscriptSegment:
    speaker_label: str
    start_seconds: float
    text: str

    def __post_init__(self) -> None:
        if not self.speaker_label.strip():
            raise ValueError("speaker_label must not be blank")
        if self.start_seconds < 0:
            raise ValueError("start_seconds must be >= 0")
        if not self.text.strip():
            raise ValueError("text must not be blank")

    @property
    def timestamp(self) -> str:
        return format_timestamp(self.start_seconds)


@dataclass(frozen=True)
class TranscriptResult:
    assemblyai_id: str
    segments: tuple[TranscriptSegment, ...]
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.assemblyai_id.strip():
            raise ValueError("assemblyai_id must not be blank")
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


def format_timestamp(seconds: float) -> str:
    whole_seconds = int(seconds)
    hours, remainder = divmod(whole_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"

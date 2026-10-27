"""Typed local model, progress, and timestamp boundaries without SDK imports."""

from __future__ import annotations

import math
from dataclasses import dataclass


class LocalTranscriptionError(RuntimeError):
    """An actionable local-only failure safe to present without provider details."""

    def __init__(self, message: str, action: str) -> None:
        super().__init__(message)
        self.action = action


class LocalModelsUnavailable(LocalTranscriptionError):
    """Preparation is required; the requested recording should remain pending."""


class LocalTranscriptionCancelled(LocalTranscriptionError):
    def __init__(self) -> None:
        super().__init__("Local processing was cancelled.", "Retry when you are ready.")


@dataclass(frozen=True, slots=True)
class LocalModelProgress:
    phase: str
    message: str
    completed_bytes: int | None = None
    total_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class LocalBackendStatus:
    supported: bool
    runtime_available: bool
    models_ready: bool
    summary: str
    action: str


def validate_interval(start: float, end: float) -> None:
    if not all(math.isfinite(value) for value in (start, end)) or start < 0 or end < start:
        raise ValueError("timestamps must be finite, ordered, and nonnegative")


@dataclass(frozen=True, slots=True)
class ASRWord:
    text: str
    start: float | None
    end: float | None

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("word text is required")
        for value in (self.start, self.end):
            if value is not None and (not math.isfinite(value) or value < 0):
                raise ValueError("word timestamps must be finite and nonnegative")
        if self.start is not None and self.end is not None:
            validate_interval(self.start, self.end)


@dataclass(frozen=True, slots=True)
class ASRSegment:
    start: float
    end: float
    text: str
    words: tuple[ASRWord, ...] = ()

    def __post_init__(self) -> None:
        validate_interval(self.start, self.end)
        if not self.text.strip():
            raise ValueError("segment text is required")


@dataclass(frozen=True, slots=True)
class DiarizationTurn:
    start: float
    end: float
    speaker: str

    def __post_init__(self) -> None:
        validate_interval(self.start, self.end)
        if not self.speaker.strip():
            raise ValueError("speaker label is required")


@dataclass(frozen=True, slots=True)
class LocalTranscriptionOutput:
    segments: tuple[ASRSegment, ...]
    turns: tuple[DiarizationTurn, ...]
    language: str
    duration_seconds: float

    def __post_init__(self) -> None:
        if not self.segments or not self.turns:
            raise ValueError("completed recognition and diarization are required")
        if not math.isfinite(self.duration_seconds) or self.duration_seconds <= 0:
            raise ValueError("audio duration is required")
        limit = self.duration_seconds + 2
        for interval in (*self.segments, *self.turns):
            if interval.end > limit:
                raise ValueError("timestamp exceeds audio duration")
        for segment in self.segments:
            for word in segment.words:
                for value in (word.start, word.end):
                    if value is not None and (
                        not math.isfinite(value) or value < 0 or value > limit
                    ):
                        raise ValueError("word timestamp exceeds audio duration")

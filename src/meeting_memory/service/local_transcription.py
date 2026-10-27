"""Deterministic alignment of local recognition text and anonymous turns."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import BinaryIO, Protocol

from meeting_memory.types.local_transcription import (
    ASRSegment,
    ASRWord,
    DiarizationTurn,
    LocalModelProgress,
    LocalTranscriptionCancelled,
    LocalTranscriptionOutput,
)
from meeting_memory.types.transcript import TranscriptResult, TranscriptSegment
from meeting_memory.types.transcription import TranscriptionProvider


class LocalTranscriber(Protocol):
    def transcribe(
        self,
        audio: BinaryIO,
        *,
        progress: Callable[[LocalModelProgress], None],
        cancelled: Callable[[], bool],
    ) -> LocalTranscriptionOutput: ...


def align_local_transcript(output: LocalTranscriptionOutput, *, attempt_id: str | None = None):
    """Keep recognition text intact, with Unknown for unassigned word timing."""

    turns = tuple(sorted(output.turns, key=lambda turn: (turn.start, turn.end, turn.speaker)))
    names = {turn.speaker: None for turn in turns}
    labels = {name: f"Speaker {chr(65 + index)}" for index, name in enumerate(names)}
    segments = tuple(
        aligned for segment in output.segments for aligned in _align_segment(segment, turns, labels)
    )
    return TranscriptResult(
        segments=segments,
        provider=TranscriptionProvider.LOCAL,
        attempt_id=attempt_id,
    )


def _align_segment(segment: ASRSegment, turns, labels):
    pieces = _text_pieces(segment)
    if pieces is None:
        return (TranscriptSegment("Unknown", segment.start, segment.text),)
    groups: list[tuple[str, float, str]] = []
    for word, text in pieces:
        label = _word_label(word, turns, labels)
        start = word.start if word.start is not None else segment.start
        if groups and groups[-1][0] == label:
            previous = groups[-1]
            groups[-1] = (label, previous[1], previous[2] + text)
        else:
            groups.append((label, start, text))
    return tuple(
        TranscriptSegment(label, start, text.strip())
        for label, start, text in groups
        if text.strip()
    )


def _text_pieces(segment):
    if not segment.words:
        return None
    cursor = 0
    pieces = []
    for word in segment.words:
        text = word.text
        index = segment.text.find(text, cursor)
        if index < 0:
            text = word.text.strip()
            index = segment.text.find(text, cursor)
        if index < 0:
            return None
        end = index + len(text)
        pieces.append((word, segment.text[cursor:end]))
        cursor = end
    word, text = pieces[-1]
    pieces[-1] = (word, text + segment.text[cursor:])
    return pieces


def _word_label(word: ASRWord, turns: tuple[DiarizationTurn, ...], labels) -> str:
    if word.start is None or word.end is None:
        return "Unknown"
    overlaps: dict[str, float] = {}
    for turn in turns:
        if turn.start > word.end:
            break
        if word.start == word.end:
            value = 1.0 if turn.start <= word.start < turn.end else 0.0
        else:
            value = max(0.0, min(word.end, turn.end) - max(word.start, turn.start))
        if value > 0:
            overlaps[turn.speaker] = overlaps.get(turn.speaker, 0.0) + value
    if not overlaps:
        return "Unknown"
    speaker = min(overlaps, key=lambda name: (-overlaps[name], name))
    return labels[speaker]


class LocalTranscriptAdapter:
    """Adapt explicit legacy retries without giving local jobs remote IDs."""

    provider = TranscriptionProvider.LOCAL

    def __init__(self, client: LocalTranscriber, *, enabled: Callable[[], bool] = lambda: True):
        self._client = client
        self._enabled = enabled

    def transcribe(self, audio: BinaryIO, *, progress=lambda _event: None) -> TranscriptResult:
        output = self._client.transcribe(
            audio, progress=progress, cancelled=lambda: not self._enabled()
        )
        if not self._enabled():
            raise LocalTranscriptionCancelled()
        return align_local_transcript(output, attempt_id=uuid.uuid4().hex)

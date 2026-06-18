"""Optional speaker-label mapping helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from meeting_memory.types.transcript import TranscriptResult, TranscriptSegment

SpeakerMapping = Mapping[str, str]


def load_speaker_mapping(path: Path | None) -> dict[str, str]:
    """Load a JSON speaker mapping such as {"Speaker A": "Alex"}."""

    if path is None:
        return {}

    expanded = path.expanduser()
    if not expanded.exists():
        return {}

    try:
        raw_mapping = json.loads(expanded.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"speaker mapping is not valid JSON: {expanded}") from exc

    if not isinstance(raw_mapping, dict):
        raise ValueError("speaker mapping must be a JSON object")

    mapping: dict[str, str] = {}
    for raw_label, raw_name in raw_mapping.items():
        if not isinstance(raw_label, str) or not isinstance(raw_name, str):
            raise ValueError("speaker mapping keys and values must be strings")
        label = raw_label.strip()
        name = raw_name.strip()
        if not label or not name:
            raise ValueError("speaker mapping keys and values must not be blank")
        mapping[label] = name
    return mapping


def apply_speaker_mapping(
    transcript: TranscriptResult,
    mapping: SpeakerMapping | None,
) -> TranscriptResult:
    """Return a transcript with speaker labels replaced by mapped names."""

    if not mapping:
        return transcript

    return TranscriptResult(
        assemblyai_id=transcript.assemblyai_id,
        segments=tuple(_map_segment(segment, mapping) for segment in transcript.segments),
        error=transcript.error,
    )


def map_speaker_label(label: str, mapping: SpeakerMapping | None) -> str:
    if not mapping:
        return label
    return mapping.get(label, label)


def _map_segment(segment: TranscriptSegment, mapping: SpeakerMapping) -> TranscriptSegment:
    return TranscriptSegment(
        speaker_label=map_speaker_label(segment.speaker_label, mapping),
        start_seconds=segment.start_seconds,
        text=segment.text,
    )

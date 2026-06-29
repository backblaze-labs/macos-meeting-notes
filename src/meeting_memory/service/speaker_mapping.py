"""Speaker-label replacement helpers."""

from __future__ import annotations

from collections.abc import Mapping

from meeting_memory.types.transcript import TranscriptResult, TranscriptSegment

SpeakerMapping = Mapping[str, str]


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

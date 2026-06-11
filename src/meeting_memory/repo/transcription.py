"""AssemblyAI transcription adapter."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from meeting_memory.config.settings import Settings
from meeting_memory.types.transcript import TranscriptResult, TranscriptSegment

DEFAULT_POLL_INTERVAL_SECONDS = 5
DEFAULT_TIMEOUT_SECONDS = 30 * 60


@dataclass(frozen=True)
class AssemblyAITranscriptionClient:
    api_key: str
    poll_interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS

    @classmethod
    def from_settings(cls, settings: Settings) -> AssemblyAITranscriptionClient:
        return cls(api_key=settings.assemblyai_api_key)

    def transcribe(self, audio_path: Path) -> TranscriptResult:
        aai = _load_assemblyai()
        aai.settings.api_key = self.api_key
        config = aai.TranscriptionConfig(speaker_labels=True)
        transcriber = aai.Transcriber()
        transcript = transcriber.transcribe(str(audio_path), config=config)
        return transcript_result_from_response(transcript)


def transcript_result_from_response(response) -> TranscriptResult:
    transcript_id = str(getattr(response, "id", "") or "assemblyai-unknown")
    status = str(getattr(response, "status", "") or "").lower()
    error = getattr(response, "error", None)
    if status == "error" or error:
        return TranscriptResult(assemblyai_id=transcript_id, segments=(), error=str(error))

    segments = tuple(_segments_from_utterances(getattr(response, "utterances", None) or ()))
    if not segments:
        return TranscriptResult(
            assemblyai_id=transcript_id,
            segments=(),
            error="No transcript segments returned.",
        )
    return TranscriptResult(assemblyai_id=transcript_id, segments=segments)


def _segments_from_utterances(utterances) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    for utterance in utterances:
        text = str(getattr(utterance, "text", "") or "").strip()
        if not text:
            continue
        speaker = getattr(utterance, "speaker", None) or getattr(utterance, "speaker_label", None)
        start_ms = float(getattr(utterance, "start", 0) or 0)
        segments.append(
            TranscriptSegment(
                speaker_label=str(speaker or "Unknown"),
                start_seconds=start_ms / 1000,
                text=text,
            )
        )
    return segments


def _load_assemblyai():
    import assemblyai

    return assemblyai

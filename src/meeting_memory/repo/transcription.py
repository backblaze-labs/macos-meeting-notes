"""AssemblyAI transcription adapter."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO

from meeting_memory.config.settings import Settings
from meeting_memory.repo.retry import DEFAULT_RETRY_DELAYS, RetryPolicy, is_likely_transient_error
from meeting_memory.types.egress import EgressPaused
from meeting_memory.types.transcript import TranscriptResult, TranscriptSegment

DEFAULT_POLL_INTERVAL_SECONDS = 5
DEFAULT_TIMEOUT_SECONDS = 30 * 60


class AssemblyAITranscriptionClient:
    __slots__ = (
        "_api_key",
        "poll_interval_seconds",
        "timeout_seconds",
        "retry_delays",
        "sleeper",
        "clock",
        "_admit_request",
    )

    def __init__(
        self,
        api_key: str,
        poll_interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        retry_delays: tuple[float, ...] = DEFAULT_RETRY_DELAYS,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        admit_request: Callable[[], bool] = lambda: True,
    ) -> None:
        object.__setattr__(self, "_api_key", api_key)
        object.__setattr__(self, "poll_interval_seconds", poll_interval_seconds)
        object.__setattr__(self, "timeout_seconds", timeout_seconds)
        object.__setattr__(self, "retry_delays", retry_delays)
        object.__setattr__(self, "sleeper", sleeper)
        object.__setattr__(self, "clock", clock)
        object.__setattr__(self, "_admit_request", admit_request)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("transcription adapter is immutable")

    @property
    def api_key(self) -> str:
        return self._api_key

    def __repr__(self) -> str:
        return "AssemblyAITranscriptionClient(api_key=<redacted>, options=<configured>)"

    @classmethod
    def from_settings(cls, settings: Settings) -> AssemblyAITranscriptionClient:
        return cls(api_key=settings.assemblyai_api_key)

    def transcribe(self, audio_path: Path | BinaryIO) -> TranscriptResult:
        """Run the legacy synchronous API; runtime uses submit then resume."""

        aai = _load_assemblyai()
        self._configure(aai)
        config = aai.TranscriptionConfig(speaker_labels=True)
        transcriber = aai.Transcriber()

        def transcribe_once():
            if hasattr(audio_path, "read"):
                audio_path.seek(0)  # type: ignore[union-attr]
                return transcriber.transcribe(audio_path, config=config)
            return transcriber.transcribe(str(audio_path), config=config)

        transcript = self._retry_policy().call(
            transcribe_once,
            is_retryable=is_likely_transient_error,
            timeout_message="AssemblyAI transcription timed out before retry",
            enabled=self._admit_request,
        )
        return transcript_result_from_response(transcript)

    def submit(self, audio: BinaryIO) -> str:
        """Create one provider job and return its ID before polling."""

        aai = _load_assemblyai()
        self._configure(aai)
        config = aai.TranscriptionConfig(speaker_labels=True)
        transcriber = aai.Transcriber()
        audio.seek(0)
        if not self._admit_request():
            raise EgressPaused("Transcription provider operation is disabled")
        transcript = transcriber.submit(audio, config=config)
        job_id = str(getattr(transcript, "id", "") or "").strip()
        if not job_id:
            raise RuntimeError("AssemblyAI submission returned no job ID")
        return job_id

    def resume(self, job_id: str) -> TranscriptResult:
        """Wait for the exact previously persisted provider job."""

        identifier = job_id.strip()
        if not identifier:
            raise ValueError("AssemblyAI job ID must not be blank")
        aai = _load_assemblyai()
        self._configure(aai)
        transcript = self._retry_policy().call(
            lambda: aai.Transcript.get_by_id(identifier),
            is_retryable=is_likely_transient_error,
            timeout_message="AssemblyAI transcription timed out before retry",
            enabled=self._admit_request,
        )
        return transcript_result_from_response(transcript)

    def _retry_policy(self) -> RetryPolicy:
        return RetryPolicy(
            delays=self.retry_delays,
            sleeper=self.sleeper,
            clock=self.clock,
            timeout_seconds=float(self.timeout_seconds),
        )

    def _configure(self, aai) -> None:
        _configure_assemblyai_settings(
            aai.settings,
            api_key=self.api_key,
            poll_interval_seconds=self.poll_interval_seconds,
            timeout_seconds=self.timeout_seconds,
        )


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


def _configure_assemblyai_settings(
    settings,
    *,
    api_key: str,
    poll_interval_seconds: int,
    timeout_seconds: int,
) -> None:
    settings.api_key = api_key
    _set_existing_float(settings, "polling_interval", poll_interval_seconds)
    _set_existing_float(settings, "sync_http_timeout", timeout_seconds)
    _cap_existing_http_timeout(settings, timeout_seconds)


def _set_existing_float(settings, name: str, value: float) -> None:
    if hasattr(settings, name):
        setattr(settings, name, float(value))


def _cap_existing_http_timeout(settings, timeout_seconds: int) -> None:
    if not hasattr(settings, "http_timeout"):
        return
    current = getattr(settings, "http_timeout", None)
    try:
        value = min(float(current), float(timeout_seconds))
    except (TypeError, ValueError):
        value = float(timeout_seconds)
    setattr(settings, "http_timeout", value)

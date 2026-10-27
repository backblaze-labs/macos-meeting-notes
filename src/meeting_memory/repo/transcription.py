"""AssemblyAI transcription adapter."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO

from meeting_memory.config.settings import Settings
from meeting_memory.repo.assemblyai_session import assemblyai_session
from meeting_memory.repo.retry import DEFAULT_RETRY_DELAYS, is_likely_transient_error
from meeting_memory.types.egress import EgressPaused
from meeting_memory.types.transcript import TranscriptResult, TranscriptSegment
from meeting_memory.types.transcription import TranscriptionProvider

DEFAULT_POLL_INTERVAL_SECONDS = 5
DEFAULT_TIMEOUT_SECONDS = 30 * 60


class AssemblyAITranscriptionClient:
    provider = TranscriptionProvider.ASSEMBLYAI

    __slots__ = (
        "_api_key",
        "poll_interval_seconds",
        "timeout_seconds",
        "retry_delays",
        "sleeper",
        "clock",
        "_admit_request",
        "external_processing_accepted",
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
        external_processing_accepted: bool = False,
    ) -> None:
        object.__setattr__(self, "_api_key", api_key)
        object.__setattr__(self, "poll_interval_seconds", poll_interval_seconds)
        object.__setattr__(self, "timeout_seconds", timeout_seconds)
        object.__setattr__(self, "retry_delays", retry_delays)
        object.__setattr__(self, "sleeper", sleeper)
        object.__setattr__(self, "clock", clock)
        object.__setattr__(self, "_admit_request", admit_request)
        object.__setattr__(self, "external_processing_accepted", external_processing_accepted)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("transcription adapter is immutable")

    @property
    def api_key(self) -> str:
        return self._api_key

    def __repr__(self) -> str:
        return "AssemblyAITranscriptionClient(api_key=<redacted>, options=<configured>)"

    @classmethod
    def from_settings(cls, settings: Settings) -> AssemblyAITranscriptionClient:
        return cls(
            api_key=settings.assemblyai_api_key,
            external_processing_accepted=(
                getattr(settings, "transcription_provider", "local") == "assemblyai"
                and getattr(settings, "assemblyai_consent", None) == "external-audio-v1"
            ),
        )

    def transcribe(self, audio_path: Path | BinaryIO) -> TranscriptResult:
        """Use the guarded submission and polling path for explicit legacy retries."""
        deadline = self.clock() + self.timeout_seconds
        self._before_request(deadline)
        if isinstance(audio_path, Path):
            with audio_path.open("rb") as audio:
                identifier = self._submit(audio, deadline)
        else:
            identifier = self._submit(audio_path, deadline)
        return self._resume(identifier, deadline)

    def submit(self, audio: BinaryIO) -> str:
        """Guard upload and create separately; never retry an ambiguous create."""
        return self._submit(audio, self.clock() + self.timeout_seconds)

    def _submit(self, audio, deadline):
        self._before_request(deadline)
        aai = _load_assemblyai()
        with assemblyai_session(
            aai, self.api_key, self.poll_interval_seconds, lambda: self._before_request(deadline)
        ) as client:
            transcriber = aai.Transcriber(client=client)

            def upload():
                audio.seek(0)
                return transcriber.upload_file(audio)

            url = self._request(upload, deadline)
            transcript = self._request(
                lambda: transcriber.submit(
                    url, config=aai.TranscriptionConfig(speaker_labels=True)
                ),
                deadline,
                retry=False,
                retain_result=True,
            )
            identifier = str(getattr(transcript, "id", "") or "").strip()
            if not identifier:
                raise RuntimeError("AssemblyAI submission returned no job ID")
            return identifier

    def resume(self, job_id: str) -> TranscriptResult:
        return self._resume(job_id, self.clock() + self.timeout_seconds)

    def _resume(self, job_id, deadline):
        identifier = job_id.strip()
        if not identifier:
            raise ValueError("AssemblyAI job ID must not be blank")
        self._before_request(deadline)
        aai = _load_assemblyai()
        with assemblyai_session(
            aai, self.api_key, self.poll_interval_seconds, lambda: self._before_request(deadline)
        ) as client:
            while True:
                response = self._request(
                    lambda: aai.api.get_transcript(client.http_client, identifier),
                    deadline,
                )
                if str(getattr(response, "id", "") or "").strip() != identifier:
                    raise RuntimeError("AssemblyAI returned a different transcript job")
                status = _response_status(response)
                if status in {"completed", "error"}:
                    return transcript_result_from_response(response)
                if status not in {"queued", "processing"}:
                    raise RuntimeError("AssemblyAI returned an unknown transcript state")
                self._sleep(self.poll_interval_seconds, deadline)

    def _request(self, operation, deadline, *, retry=True, retain_result=False):
        delays = self.retry_delays if retry else ()
        for delay in (*delays, None):
            self._before_request(deadline)
            try:
                result = operation()
            except Exception as exc:
                if delay is None or not is_likely_transient_error(exc):
                    raise
                self._sleep(delay, deadline)
            else:
                if not retain_result:
                    self._remaining(deadline)
                return result
        raise RuntimeError("Unreachable AssemblyAI retry state")

    def _sleep(self, delay, deadline):
        remaining = self._before_request(deadline)
        self.sleeper(min(float(delay), remaining))
        self._before_request(deadline)

    def _remaining(self, deadline):
        remaining = deadline - self.clock()
        if remaining <= 0:
            raise TimeoutError(
                "AssemblyAI transcription timed out; the existing job ID is retained."
            )
        return remaining

    def _before_request(self, deadline):
        if self.external_processing_accepted is not True:
            raise PermissionError("Explicit AssemblyAI external-processing acceptance is required.")
        if not self._admit_request():
            raise EgressPaused("Transcription provider operation is disabled")
        return self._remaining(deadline)


def transcript_result_from_response(response) -> TranscriptResult:
    transcript_id = str(getattr(response, "id", "") or "").strip()
    if not transcript_id:
        raise RuntimeError("AssemblyAI returned no transcript ID")
    status = _response_status(response)
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


def _response_status(response):
    value = getattr(response, "status", "")
    return str(getattr(value, "value", value)).lower()

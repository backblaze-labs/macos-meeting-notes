"""Provider selection and durable transcription attempt boundaries."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class TranscriptionProvider(StrEnum):
    LOCAL = "local"
    ASSEMBLYAI = "assemblyai"


ASSEMBLYAI_CONSENT_VERSION = "external-audio-v1"
NO_ASSEMBLYAI_CONSENT = "not-accepted"


@dataclass(frozen=True, slots=True)
class TranscriptionAudioIdentity:
    device: int
    inode: int
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class TranscriptionAttempt:
    provider: TranscriptionProvider
    attempt_id: str
    audio_identity: TranscriptionAudioIdentity | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.provider, TranscriptionProvider):
            raise ValueError("transcription provider must be typed")
        if re.fullmatch(r"[0-9a-f]{32}", self.attempt_id) is None:
            raise ValueError("transcription attempt must be an opaque identifier")

"""Read an optional private local transcription profile without following file links."""

import json
import os
import stat
from pathlib import Path

from meeting_memory.types.local_asr import LocalASRProfile
from meeting_memory.types.local_transcription import LocalTranscriptionError

MAX_PROFILE_BYTES = 16_384


def local_asr_profile_path() -> Path:
    return Path.home() / "Library/Application Support/meeting-memory/transcription-profile.json"


def load_local_asr_profile(path: Path | None = None) -> LocalASRProfile:
    path = path or local_asr_profile_path()
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return LocalASRProfile()
    except OSError:
        raise _profile_error() from None
    try:
        with os.fdopen(descriptor, "rb") as source:
            info = os.fstat(source.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_mode & 0o077
                or info.st_nlink != 1
                or info.st_size > MAX_PROFILE_BYTES
            ):
                raise ValueError("profile must be a private bounded regular file")
            content = source.read(MAX_PROFILE_BYTES + 1)
            if len(content) > MAX_PROFILE_BYTES:
                raise ValueError("profile exceeds read limit")
            return LocalASRProfile.from_json(json.loads(content))
    except (OSError, ValueError, TypeError, UnicodeError):
        raise _profile_error() from None


def _profile_error() -> LocalTranscriptionError:
    return LocalTranscriptionError(
        "The local transcription profile could not be loaded.",
        "Check transcription-profile.json format and private permissions, then retry. "
        "Your recording is preserved.",
    )

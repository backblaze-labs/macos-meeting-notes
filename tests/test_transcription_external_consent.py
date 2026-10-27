"""Explicit consent is checked before loading the external SDK."""

from io import BytesIO
from pathlib import Path

import pytest

from meeting_memory.repo.transcription import AssemblyAITranscriptionClient


@pytest.mark.parametrize(
    "method,args",
    [
        ("submit", (BytesIO(b"audio"),)),
        ("resume", ("old-id",)),
        ("transcribe", (Path("audio.m4a"),)),
    ],
)
def test_inherited_key_cannot_load_sdk_or_make_requests(monkeypatch, method, args):
    def forbidden():
        raise AssertionError("SDK loaded without external consent")

    monkeypatch.setattr("meeting_memory.repo.transcription._load_assemblyai", forbidden)
    client = AssemblyAITranscriptionClient("old-key")
    with pytest.raises(PermissionError, match="acceptance"):
        getattr(client, method)(*args)

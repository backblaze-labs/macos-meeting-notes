"""Provider adapter representations never disclose composed credentials."""

from __future__ import annotations

from dataclasses import asdict

import pytest

from meeting_memory.repo.b2_client import B2S3Client
from meeting_memory.repo.summarizer import ClaudeSummarizer
from meeting_memory.repo.transcription import AssemblyAITranscriptionClient


@pytest.mark.parametrize(
    "adapter",
    [
        AssemblyAITranscriptionClient("assembly-secret-sentinel"),
        B2S3Client(
            "b2-id-secret-sentinel",
            "b2-key-secret-sentinel",
            "https://s3.example.invalid",
            "region",
            "bucket",
        ),
        ClaudeSummarizer("notes-secret-sentinel"),
    ],
)
def test_adapter_repr_str_and_dataclass_serialization_are_redacted(adapter) -> None:
    sentinels = (
        "assembly-secret-sentinel",
        "b2-id-secret-sentinel",
        "b2-key-secret-sentinel",
        "notes-secret-sentinel",
    )

    assert all(secret not in repr(adapter) for secret in sentinels)
    assert all(secret not in str(adapter) for secret in sentinels)
    with pytest.raises(TypeError):
        asdict(adapter)

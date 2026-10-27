"""Shared explicit fakes for deterministic provider-readiness tests."""

import pytest

from meeting_memory.types.local_transcription import LocalBackendStatus


@pytest.fixture
def local_models_ready(monkeypatch):
    """Represent a supported, prepared Mac without loading MLX, weights, or networking."""
    monkeypatch.setattr(
        "meeting_memory.service.readiness_transcription.inspect_local_backend",
        lambda **_kwargs: LocalBackendStatus(
            True, True, True, "Local transcription models are available.", ""
        ),
    )

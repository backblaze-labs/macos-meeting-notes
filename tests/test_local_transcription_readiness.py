"""Local readiness is capability-scoped and never selects cloud as recovery."""

import pytest

from meeting_memory.config.runtime import RuntimeSettings
from meeting_memory.service import readiness_transcription
from meeting_memory.types.capabilities import CapabilityState
from meeting_memory.types.local_transcription import LocalBackendStatus


@pytest.mark.parametrize(
    ("status", "state"),
    [
        (
            LocalBackendStatus(False, False, False, "Unsupported Mac.", "Use a supported Mac."),
            CapabilityState.FAILED,
        ),
        (
            LocalBackendStatus(True, False, False, "Runtime missing.", "Update the app."),
            CapabilityState.FAILED,
        ),
        (
            LocalBackendStatus(True, True, False, "Models missing.", "Prepare Local Models."),
            CapabilityState.UNCONFIGURED,
        ),
        (LocalBackendStatus(True, True, True, "Local models ready.", ""), CapabilityState.READY),
    ],
)
def test_local_status_never_requires_cloud_key(monkeypatch, status, state):
    calls = []

    def inspect(**kwargs):
        calls.append(kwargs)
        return status

    monkeypatch.setattr(readiness_transcription, "inspect_local_backend", inspect)
    settings = RuntimeSettings(_env_file=None, assemblyai_api_key="inherited-unused")
    result = readiness_transcription.transcription_status(settings)
    assert result.state is state
    assert result.summary == status.summary
    assert calls == [{"probe_metal": True}]
    assert "inherited-unused" not in repr(result)
    if state is not CapabilityState.READY:
        assert result.action == status.action


def test_explicit_cloud_readiness_does_not_probe_or_fallback_to_local(monkeypatch):
    def unexpected(**kwargs):
        raise AssertionError("External provider must not inspect or activate Local")

    monkeypatch.setattr(readiness_transcription, "inspect_local_backend", unexpected)
    settings = RuntimeSettings(
        _env_file=None,
        transcription_provider="assemblyai",
        assemblyai_consent="external-audio-v1",
        assemblyai_api_key="explicit-key",
    )
    result = readiness_transcription.transcription_status(settings)
    assert result.state is CapabilityState.READY
    assert "external" in result.summary


def test_cloud_without_acceptance_remains_unconfigured(monkeypatch):
    monkeypatch.setattr(
        readiness_transcription,
        "inspect_local_backend",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("No fallback")),
    )
    settings = RuntimeSettings(
        _env_file=None, transcription_provider="assemblyai", assemblyai_api_key="old-key"
    )
    assert (
        readiness_transcription.transcription_status(settings).state is CapabilityState.UNCONFIGURED
    )

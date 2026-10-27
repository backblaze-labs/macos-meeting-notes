"""Composition selects one explicit transcription backend without fallback."""

from types import SimpleNamespace

from meeting_memory.types.transcription import TranscriptionProvider
from meeting_memory.ui import runtime_app


def test_default_local_never_constructs_assemblyai(monkeypatch):
    calls = []
    local = object()
    monkeypatch.setattr(runtime_app, "LocalTranscriptionClient", lambda: local)
    monkeypatch.setattr(
        runtime_app,
        "AssemblyAITranscriptionClient",
        lambda *args, **kwargs: calls.append("assemblyai"),
    )
    config = SimpleNamespace(provider=TranscriptionProvider.LOCAL)
    assert runtime_app._transcription_client(SimpleNamespace(transcription=config)) is local
    assert calls == []


def test_local_constructor_failure_never_falls_back(monkeypatch):
    calls = []

    def unavailable():
        raise RuntimeError("private local constructor detail")

    monkeypatch.setattr(runtime_app, "LocalTranscriptionClient", unavailable)
    monkeypatch.setattr(
        runtime_app,
        "AssemblyAITranscriptionClient",
        lambda *args, **kwargs: calls.append("assemblyai"),
    )
    config = SimpleNamespace(provider=TranscriptionProvider.LOCAL)
    assert runtime_app._transcription_client(SimpleNamespace(transcription=config)) is None
    assert calls == []


def test_explicit_external_selection_forwards_accepted_notice(monkeypatch):
    calls = []
    external = object()

    def construct(key, **kwargs):
        calls.append((key, kwargs["external_processing_accepted"]))
        return external

    monkeypatch.setattr(runtime_app, "AssemblyAITranscriptionClient", construct)
    monkeypatch.setattr(
        runtime_app,
        "LocalTranscriptionClient",
        lambda: (_ for _ in ()).throw(AssertionError("No implicit Local fallback")),
    )
    config = SimpleNamespace(
        provider=TranscriptionProvider.ASSEMBLYAI,
        api_key="explicit-external-key",
        external_processing_accepted=True,
    )
    assert runtime_app._transcription_client(SimpleNamespace(transcription=config)) is external
    assert calls == [("explicit-external-key", True)]


def test_disabled_transcription_constructs_neither_backend(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("Disabled capability must construct no client")

    monkeypatch.setattr(runtime_app, "AssemblyAITranscriptionClient", unexpected)
    monkeypatch.setattr(runtime_app, "LocalTranscriptionClient", unexpected)
    assert runtime_app._transcription_client(SimpleNamespace(transcription=None)) is None

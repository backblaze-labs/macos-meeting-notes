"""Tests for the AssemblyAI transcription adapter."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from meeting_memory.config.settings import Settings
from meeting_memory.repo import transcription
from meeting_memory.repo.transcription import AssemblyAITranscriptionClient


def test_assemblyai_transcription_uses_speaker_labels(tmp_path: Path, monkeypatch) -> None:
    fake_aai = FakeAssemblyAI(
        response=SimpleNamespace(
            id="tx-123",
            status="completed",
            utterances=(
                SimpleNamespace(speaker="Speaker A", start=5000, text="Hello."),
                SimpleNamespace(speaker="Speaker B", start=12000, text="Hi."),
            ),
        )
    )
    monkeypatch.setattr(transcription, "_load_assemblyai", lambda: fake_aai)

    client = AssemblyAITranscriptionClient(api_key="assembly-key")
    result = client.transcribe(tmp_path / "recording.m4a")

    assert fake_aai.settings.api_key == "assembly-key"
    assert fake_aai.last_config.speaker_labels is True
    assert fake_aai.last_transcriber.audio_path == str(tmp_path / "recording.m4a")
    assert result.assemblyai_id == "tx-123"
    assert result.participants == ("Speaker A", "Speaker B")
    assert result.segments[0].start_seconds == 5


def test_assemblyai_transcription_returns_error_result(monkeypatch) -> None:
    fake_aai = FakeAssemblyAI(
        response=SimpleNamespace(id="tx-err", status="error", error="bad audio", utterances=())
    )
    monkeypatch.setattr(transcription, "_load_assemblyai", lambda: fake_aai)

    result = AssemblyAITranscriptionClient(api_key="assembly-key").transcribe(Path("bad.m4a"))

    assert result.assemblyai_id == "tx-err"
    assert result.error == "bad audio"
    assert result.segments == ()


def test_assemblyai_client_from_settings() -> None:
    settings = Settings(
        b2_application_key_id="key-id",
        b2_application_key="secret",
        b2_endpoint="https://s3.example.com",
        b2_region="us-west-004",
        b2_bucket_name="bucket",
        assemblyai_api_key="assembly-key",
    )

    assert AssemblyAITranscriptionClient.from_settings(settings).api_key == "assembly-key"


class FakeConfig:
    def __init__(self, *, speaker_labels: bool):
        self.speaker_labels = speaker_labels


class FakeTranscriber:
    def __init__(self, response):
        self.response = response
        self.audio_path: str | None = None
        self.config = None

    def transcribe(self, audio_path: str, *, config):
        self.audio_path = audio_path
        self.config = config
        return self.response


class FakeAssemblyAI:
    def __init__(self, response):
        self.response = response
        self.settings = SimpleNamespace(api_key=None)
        self.last_config = None
        self.last_transcriber = None

    def TranscriptionConfig(self, *, speaker_labels: bool):
        self.last_config = FakeConfig(speaker_labels=speaker_labels)
        return self.last_config

    def Transcriber(self):
        self.last_transcriber = FakeTranscriber(self.response)
        return self.last_transcriber

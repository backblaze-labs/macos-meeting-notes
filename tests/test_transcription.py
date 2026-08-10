"""Tests for the AssemblyAI transcription adapter."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest

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

    client = AssemblyAITranscriptionClient(
        api_key="assembly-key",
        poll_interval_seconds=9,
        timeout_seconds=7,
    )
    result = client.transcribe(tmp_path / "recording.m4a")

    assert fake_aai.settings.api_key == "assembly-key"
    assert fake_aai.settings.polling_interval == 9.0
    assert fake_aai.settings.sync_http_timeout == 7.0
    assert fake_aai.settings.http_timeout == 7.0
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


def test_legacy_transcription_passes_binary_stream_to_sdk(monkeypatch) -> None:
    fake_aai = FakeAssemblyAI(
        response=SimpleNamespace(
            id="tx-stream",
            status="completed",
            utterances=(SimpleNamespace(speaker="A", start=0, text="Ready."),),
        )
    )
    monkeypatch.setattr(transcription, "_load_assemblyai", lambda: fake_aai)
    audio = BytesIO(b"private audio")

    result = AssemblyAITranscriptionClient(api_key="assembly-key").transcribe(audio)

    assert result.assemblyai_id == "tx-stream"
    assert fake_aai.last_transcriber.audio_path is audio
    assert not isinstance(fake_aai.last_transcriber.audio_path, str)


def test_assemblyai_transcription_retries_transient_errors(tmp_path: Path, monkeypatch) -> None:
    fake_aai = FakeAssemblyAI(
        response=SimpleNamespace(
            id="tx-retry",
            status="completed",
            utterances=(SimpleNamespace(speaker="Speaker A", start=0, text="Recovered."),),
        ),
        failures=(TimeoutError("temporary timeout"),),
    )
    sleeps: list[float] = []
    monkeypatch.setattr(transcription, "_load_assemblyai", lambda: fake_aai)

    result = AssemblyAITranscriptionClient(
        api_key="assembly-key",
        retry_delays=(0.25,),
        sleeper=sleeps.append,
    ).transcribe(tmp_path / "recording.m4a")

    assert result.assemblyai_id == "tx-retry"
    assert sleeps == [0.25]
    assert fake_aai.last_transcriber.attempts == 2


def test_assemblyai_client_from_settings() -> None:
    settings = Settings(
        _env_file=None,
        b2_application_key_id="key-id",
        b2_application_key="secret",
        b2_endpoint="https://s3.example.com",
        b2_region="us-west-004",
        b2_bucket_name="bucket",
        assemblyai_api_key="assembly-key",
    )

    assert AssemblyAITranscriptionClient.from_settings(settings).api_key == "assembly-key"


def test_runtime_submit_returns_job_id_before_resume(monkeypatch) -> None:
    fake_aai = FakeSplitAssemblyAI(
        SimpleNamespace(
            id="tx-split",
            status="completed",
            utterances=(SimpleNamespace(speaker="A", start=0, text="Ready."),),
        )
    )
    monkeypatch.setattr(transcription, "_load_assemblyai", lambda: fake_aai)
    client = AssemblyAITranscriptionClient(api_key="assembly-key")

    assert client.submit(BytesIO(b"audio")) == "tx-split"
    assert fake_aai.resumed_ids == []
    assert client.resume("tx-split").assemblyai_id == "tx-split"
    assert fake_aai.resumed_ids == ["tx-split"]


def test_runtime_submit_does_not_retry_ambiguous_create_timeout(monkeypatch) -> None:
    attempts = 0

    class TimeoutTranscriber:
        def submit(self, _audio, *, config):
            nonlocal attempts
            attempts += 1
            assert config.speaker_labels is True
            raise TimeoutError("job may already exist")

    fake_aai = FakeSplitAssemblyAI(SimpleNamespace(id="unused"))
    fake_aai.Transcriber = TimeoutTranscriber
    monkeypatch.setattr(transcription, "_load_assemblyai", lambda: fake_aai)

    with pytest.raises(TimeoutError, match="may already exist"):
        AssemblyAITranscriptionClient(api_key="key").submit(BytesIO(b"audio"))

    assert attempts == 1


class FakeConfig:
    def __init__(self, *, speaker_labels: bool):
        self.speaker_labels = speaker_labels


class FakeTranscriber:
    def __init__(self, response, failures=()):
        self.response = response
        self.failures = list(failures)
        self.attempts = 0
        self.audio_path = None
        self.config = None

    def transcribe(self, audio_path, *, config):
        self.attempts += 1
        self.audio_path = audio_path
        self.config = config
        if self.failures:
            raise self.failures.pop(0)
        return self.response


class FakeAssemblyAI:
    def __init__(self, response, failures=()):
        self.response = response
        self.failures = failures
        self.settings = SimpleNamespace(
            api_key=None,
            polling_interval=3.0,
            sync_http_timeout=60.0,
            http_timeout=30.0,
        )
        self.last_config = None
        self.last_transcriber = None

    def TranscriptionConfig(self, *, speaker_labels: bool):
        self.last_config = FakeConfig(speaker_labels=speaker_labels)
        return self.last_config

    def Transcriber(self):
        self.last_transcriber = FakeTranscriber(self.response, self.failures)
        return self.last_transcriber


class FakeSplitTranscriber:
    def __init__(self, response):
        self.response = response

    def submit(self, _audio_path: str, *, config):
        assert config.speaker_labels is True
        return self.response


class FakeSplitAssemblyAI(FakeAssemblyAI):
    def __init__(self, response):
        super().__init__(response)
        self.resumed_ids: list[str] = []
        owner = self

        class Transcript:
            @staticmethod
            def get_by_id(job_id: str):
                owner.resumed_ids.append(job_id)
                return owner.response

        self.Transcript = Transcript

    def Transcriber(self):
        return FakeSplitTranscriber(self.response)

"""Tests for the AssemblyAI transcription adapter."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from transcription_fakes import FakeAssemblyAI

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
        external_processing_accepted=True,
        api_key="assembly-key",
        poll_interval_seconds=9,
        timeout_seconds=7,
    )
    (tmp_path / "recording.m4a").write_bytes(b"audio")
    result = client.transcribe(tmp_path / "recording.m4a")

    assert fake_aai.settings.api_key == "global-key"
    assert fake_aai.clients[0].settings.api_key == "assembly-key"
    assert fake_aai.clients[0].settings.polling_interval == 9.0
    assert 0 < fake_aai.clients[0].settings.http_timeout <= 7.0
    assert all(client.http_client.closed for client in fake_aai.clients)
    assert fake_aai.last_config.speaker_labels is True
    assert fake_aai.last_transcriber.audio_path.closed
    assert result.assemblyai_id == "tx-123"
    assert result.participants == ("Speaker A", "Speaker B")
    assert result.segments[0].start_seconds == 5


def test_assemblyai_transcription_returns_error_result(monkeypatch) -> None:
    fake_aai = FakeAssemblyAI(
        response=SimpleNamespace(id="tx-err", status="error", error="bad audio", utterances=())
    )
    monkeypatch.setattr(transcription, "_load_assemblyai", lambda: fake_aai)

    result = AssemblyAITranscriptionClient(
        external_processing_accepted=True, api_key="assembly-key"
    ).transcribe(BytesIO(b"bad audio"))

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

    result = AssemblyAITranscriptionClient(
        external_processing_accepted=True, api_key="assembly-key"
    ).transcribe(audio)

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

    (tmp_path / "recording.m4a").write_bytes(b"audio")
    result = AssemblyAITranscriptionClient(
        external_processing_accepted=True,
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
    fake_aai = FakeAssemblyAI(
        SimpleNamespace(
            id="tx-split",
            status="completed",
            utterances=(SimpleNamespace(speaker="A", start=0, text="Ready."),),
        )
    )
    monkeypatch.setattr(transcription, "_load_assemblyai", lambda: fake_aai)
    client = AssemblyAITranscriptionClient(
        external_processing_accepted=True, api_key="assembly-key"
    )

    assert client.submit(BytesIO(b"audio")) == "tx-split"
    assert fake_aai.resumed_ids == []
    assert client.resume("tx-split").assemblyai_id == "tx-split"
    assert fake_aai.resumed_ids == ["tx-split"]


def test_runtime_submit_does_not_retry_ambiguous_create_timeout(monkeypatch) -> None:
    attempts = 0

    class TimeoutTranscriber:
        def __init__(self, *, client):
            self.client = client

        def upload_file(self, audio):
            return "https://uploads.assemblyai.com/audio"

        def submit(self, _audio, *, config):
            nonlocal attempts
            attempts += 1
            assert config.speaker_labels is True
            raise TimeoutError("job may already exist")

    fake_aai = FakeAssemblyAI(SimpleNamespace(id="unused"))
    fake_aai.Transcriber = TimeoutTranscriber
    monkeypatch.setattr(transcription, "_load_assemblyai", lambda: fake_aai)

    with pytest.raises(TimeoutError, match="may already exist"):
        AssemblyAITranscriptionClient(external_processing_accepted=True, api_key="key").submit(
            BytesIO(b"audio")
        )

    assert attempts == 1

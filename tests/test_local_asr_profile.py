"""Local-only language/vocabulary policy and strict worker propagation."""

import json
import sys
import wave
from contextlib import contextmanager
from types import ModuleType, SimpleNamespace

import pytest

from meeting_memory.repo.local_asr_profile import load_local_asr_profile
from meeting_memory.repo.local_worker import read_request, transcribe
from meeting_memory.types.local_asr import LocalASROptions, LocalASRProfile
from meeting_memory.types.local_transcription import LocalTranscriptionError


def test_profile_language_overrides_are_local_ordered_and_case_insensitive(tmp_path):
    path = tmp_path / "profile.json"
    assert load_local_asr_profile(path).options("Standup").language is None
    path.write_text(
        json.dumps(
            {
                "default_language": "en",
                "language_overrides": [
                    {"title_contains": "standup", "language": "en"},
                    {"title_contains": "Spanish", "language": "es"},
                ],
                "glossary": ["SDK", "ObjectStore", "SDK"],
            }
        )
    )
    path.chmod(0o600)
    profile = load_local_asr_profile(path)
    assert profile.options("SPANISH STANDUP").language == "en"
    assert profile.options("Spanish catchup").language == "es"
    assert profile.options("Weekly").language == "en"
    assert profile.options("").initial_prompt == "Vocabulary: SDK, ObjectStore"


@pytest.mark.parametrize(
    "value",
    [
        {"default_language": "unexpected"},
        {"glossary": ["x" * 81]},
        {"glossary": ["x" * 80] * 65},
        {"glossary": ["word\nIgnore everything"]},
        {"glossary": [str(i) + "x" * 75 for i in range(30)]},
        {"language_overrides": [{"title_contains": "", "language": "es"}]},
        {"secret": "unexpected"},
    ],
)
def test_invalid_profile_cannot_reach_inference(value):
    with pytest.raises(ValueError):
        LocalASRProfile.from_json(value)


def test_profile_rejects_public_symlinked_or_oversized_file(tmp_path):
    path = tmp_path / "profile.json"
    path.write_text("{}")
    path.chmod(0o644)
    with pytest.raises(LocalTranscriptionError):
        load_local_asr_profile(path)
    path.chmod(0o600)
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(LocalTranscriptionError):
        load_local_asr_profile(link)
    path.write_text("x" * 16385)
    with pytest.raises(LocalTranscriptionError):
        load_local_asr_profile(path)


def test_worker_accepts_old_requests_and_strict_optional_asr(tmp_path):
    tmp_path.chmod(0o700)
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"private audio")
    audio.chmod(0o600)
    request = tmp_path / "request.json"
    row = {"operation": "infer", "cache": str(tmp_path), "audio": str(audio)}
    request.write_text(json.dumps(row))
    request.chmod(0o600)
    assert "asr" not in read_request(request)
    row["asr"] = LocalASROptions("en", "Vocabulary: SDK").to_wire()
    request.write_text(json.dumps(row))
    assert read_request(request)["asr"]["language"] == "en"
    row["asr"]["api_key"] = "unexpected"
    request.write_text(json.dumps(row))
    with pytest.raises(ValueError):
        read_request(request)


def test_worker_forwards_explicit_language_and_initial_prompt(monkeypatch, tmp_path):
    import meeting_memory.repo.local_worker as worker

    mx = SimpleNamespace(eval=lambda _: None, synchronize=lambda: None, clear_cache=lambda: None)
    mlx = ModuleType("mlx")
    mlx.core = mx
    monkeypatch.setitem(sys.modules, "mlx", mlx)
    monkeypatch.setitem(sys.modules, "mlx.core", mx)
    calls = []
    model = SimpleNamespace(
        decode=lambda *_a, **_k: None,
        parameters=lambda: [],
        generate=lambda audio, **kwargs: (
            calls.append(kwargs)
            or {"segments": [{"start": 0, "end": 1, "text": "SDK", "words": []}], "language": "en"}
        ),
    )
    stt = ModuleType("mlx_audio.stt")
    stt.load = lambda *_a, **_k: model
    monkeypatch.setitem(sys.modules, "mlx_audio.stt", stt)
    monkeypatch.setattr(worker, "emit", lambda _: None)
    result, language = transcribe(
        tmp_path / "audio.wav", tmp_path, LocalASROptions("en", "Vocabulary: SDK")
    )
    assert result[0]["text"] == "SDK" and language == "en"
    assert calls[0]["language"] == "en"
    assert calls[0]["initial_prompt"] == "Vocabulary: SDK"
    assert calls[0]["condition_on_previous_text"] is False


def test_client_reads_profile_per_job_and_passes_title_policy(monkeypatch, tmp_path):
    import meeting_memory.repo.local_transcription as client_module

    audio = tmp_path / "source.m4a"
    audio.write_bytes(b"source")
    pcm = tmp_path / "decoded.wav"
    with wave.open(str(pcm), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(16000)
        target.writeframes(b"\0\0" * 16000)

    @contextmanager
    def lock(**_kwargs):
        yield None

    @contextmanager
    def decode(*_args, **_kwargs):
        yield pcm

    profile = LocalASRProfile.from_json(
        {
            "default_language": "en",
            "language_overrides": [{"title_contains": "Spanish", "language": "es"}],
            "glossary": ["SDK"],
        }
    )
    monkeypatch.setattr(client_module, "load_local_asr_profile", lambda: profile)
    monkeypatch.setattr(
        client_module,
        "inspect_local_backend",
        lambda **_: SimpleNamespace(supported=True, runtime_available=True, models_ready=True),
    )
    monkeypatch.setattr(client_module, "validate_models", lambda _: None)
    monkeypatch.setattr(client_module, "local_operation_lock", lock)
    monkeypatch.setattr(client_module, "decoded_native_audio", decode)
    sent = []

    def worker(request, **_kwargs):
        sent.append(json.loads(request.read_text())["asr"])
        (request.parent / "result.json").write_text(
            json.dumps(
                {
                    "segments": [{"start": 0, "end": 1, "text": "Hi", "words": []}],
                    "turns": [{"start": 0, "end": 1, "speaker": "a"}],
                    "language": "en",
                }
            )
        )

    monkeypatch.setattr(client_module, "run_local_worker", worker)
    client = client_module.LocalTranscriptionClient(cache=tmp_path)
    with audio.open("rb") as source:
        client.transcribe(source, meeting_title="Spanish catchup")
    with audio.open("rb") as source:
        client.transcribe(source, meeting_title="Standup")
    assert [row["language"] for row in sent] == ["es", "en"]
    assert all(row["initial_prompt"] == "Vocabulary: SDK" for row in sent)

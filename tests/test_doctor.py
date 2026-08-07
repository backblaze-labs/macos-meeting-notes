"""Tests for preflight diagnostics."""

from __future__ import annotations

from meeting_memory import doctor
from meeting_memory.repo.native_audio import NativeAudioCaptureError


def test_b2_env_check_reports_missing_b2_values() -> None:
    result = doctor.check_b2_env({"B2_BUCKET_NAME": "replace-me"})

    assert result.ok is False
    assert result.name == "b2-env"
    assert "B2_APPLICATION_KEY_ID" in result.message
    assert "B2_BUCKET_NAME" in result.message
    assert result.fix is not None
    assert "B2 bucket/key" in result.fix


def test_assemblyai_env_check_reports_missing_key() -> None:
    result = doctor.check_assemblyai_env({})

    assert result.ok is False
    assert result.name == "assemblyai-env"
    assert "ASSEMBLYAI_API_KEY" in result.message


def test_google_token_check_passes_when_keychain_has_token(monkeypatch) -> None:
    class TokenStore:
        def read_token(self) -> str:
            return "token"

    monkeypatch.setattr(doctor, "_keychain_token_store_cls", lambda: TokenStore)

    result = doctor.check_google_token()

    assert result.ok is True
    assert result.warning is False
    assert result.name == "google-token"


def test_native_audio_check_passes_with_current_microphone(monkeypatch) -> None:
    monkeypatch.setattr(
        doctor,
        "check_native_capture",
        lambda: {"event": "supported", "microphone": "AirPods"},
    )

    result = doctor.check_native_audio()

    assert result.ok is True
    assert result.warning is False
    assert result.name == "native-audio"
    assert "AirPods" in result.message


def test_native_audio_check_reports_missing_helper(monkeypatch) -> None:
    monkeypatch.setattr(
        doctor,
        "check_native_capture",
        lambda: (_ for _ in ()).throw(NativeAudioCaptureError("helper missing")),
    )

    result = doctor.check_native_audio()

    assert result.ok is False
    assert result.warning is False
    assert "helper missing" in result.message
    assert result.fix is not None
    assert "make setup" in result.fix

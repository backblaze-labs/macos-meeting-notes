"""Tests for preflight diagnostics."""

from __future__ import annotations

from meeting_memory import doctor
from meeting_memory.repo.audio_device import AudioDeviceInfo


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


def test_audio_device_check_warns_when_no_inputs_are_visible(monkeypatch) -> None:
    monkeypatch.setattr(doctor, "list_audio_devices", lambda: [])

    result = doctor.check_audio_device({"AUDIO_DEVICE": "Meeting Aggregate"})

    assert result.ok is True
    assert result.warning is True
    assert "No audio input devices are visible" in result.message
    assert "AUDIO_DEVICE=Meeting Aggregate" in result.message
    assert result.fix is not None
    assert "microphone access" in result.fix


def test_audio_device_check_passes_for_configured_input_device(monkeypatch) -> None:
    monkeypatch.setattr(
        doctor,
        "list_audio_devices",
        lambda: [
            AudioDeviceInfo(index=0, name="Built-in Mic", max_input_channels=1),
            AudioDeviceInfo(index=1, name="Meeting Aggregate", max_input_channels=2),
        ],
    )

    result = doctor.check_audio_device({"AUDIO_DEVICE": "Meeting Aggregate"})

    assert result.ok is True
    assert result.warning is False
    assert result.message == "Audio device exists: Meeting Aggregate."


def test_audio_device_check_fails_when_configured_input_is_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        doctor,
        "list_audio_devices",
        lambda: [AudioDeviceInfo(index=0, name="Built-in Mic", max_input_channels=1)],
    )

    result = doctor.check_audio_device({"AUDIO_DEVICE": "Meeting Aggregate"})

    assert result.ok is False
    assert result.warning is False
    assert "Audio input device was not found: Meeting Aggregate." in result.message
    assert "Built-in Mic (1 in)" in result.message


def test_audio_device_check_fails_when_configured_device_has_no_inputs(monkeypatch) -> None:
    monkeypatch.setattr(
        doctor,
        "list_audio_devices",
        lambda: [
            AudioDeviceInfo(index=0, name="Built-in Mic", max_input_channels=1),
            AudioDeviceInfo(index=1, name="Meeting Aggregate", max_input_channels=0),
        ],
    )

    result = doctor.check_audio_device({"AUDIO_DEVICE": "Meeting Aggregate"})

    assert result.ok is False
    assert result.warning is False
    assert result.message == "Audio device exists but has no input channels: Meeting Aggregate."

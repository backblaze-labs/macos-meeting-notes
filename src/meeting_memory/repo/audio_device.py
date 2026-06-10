"""Audio-device lookup helpers."""

from __future__ import annotations


class AudioDeviceCheckUnavailable(RuntimeError):
    """Raised when sounddevice is unavailable for doctor checks."""


def list_audio_device_names() -> list[str]:
    try:
        import sounddevice
    except ModuleNotFoundError as exc:
        raise AudioDeviceCheckUnavailable(
            "sounddevice is not installed; skipping audio-device lookup."
        ) from exc

    devices = sounddevice.query_devices()
    return sorted({str(device.get("name", "")) for device in devices if device.get("name")})

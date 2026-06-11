"""Audio-device lookup helpers."""

from __future__ import annotations

from dataclasses import dataclass


class AudioDeviceCheckUnavailable(RuntimeError):
    """Raised when sounddevice is unavailable for doctor checks."""


@dataclass(frozen=True)
class AudioDeviceInfo:
    index: int
    name: str
    max_input_channels: int


def list_audio_device_names() -> list[str]:
    return [device.name for device in list_audio_devices()]


def find_audio_device(device_name: str) -> AudioDeviceInfo:
    for device in list_audio_devices():
        if device.name == device_name:
            return device
    raise LookupError(f"Audio device not found: {device_name}")


def list_audio_devices() -> list[AudioDeviceInfo]:
    try:
        import sounddevice
    except ModuleNotFoundError as exc:
        raise AudioDeviceCheckUnavailable(
            "sounddevice is not installed; skipping audio-device lookup."
        ) from exc

    devices = sounddevice.query_devices()
    return [
        AudioDeviceInfo(
            index=index,
            name=str(device.get("name", "")),
            max_input_channels=int(device.get("max_input_channels", 0)),
        )
        for index, device in enumerate(devices)
        if device.get("name")
    ]

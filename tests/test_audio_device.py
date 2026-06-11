"""Tests for audio-device lookup."""

from __future__ import annotations

import builtins
import sys
from types import SimpleNamespace

import pytest

from meeting_memory.repo.audio_device import (
    AudioDeviceCheckUnavailable,
    find_audio_device,
    list_audio_device_names,
)


def test_audio_device_lookup_uses_sounddevice(monkeypatch) -> None:
    fake_sounddevice = SimpleNamespace(
        query_devices=lambda: [
            {"name": "Built-in Mic", "max_input_channels": 1},
            {"name": "Meeting Aggregate", "max_input_channels": 2},
        ]
    )
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sounddevice)

    device = find_audio_device("Meeting Aggregate")

    assert list_audio_device_names() == ["Built-in Mic", "Meeting Aggregate"]
    assert device.index == 1
    assert device.name == "Meeting Aggregate"
    assert device.max_input_channels == 2


def test_audio_device_lookup_reports_missing_device(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "sounddevice", SimpleNamespace(query_devices=lambda: []))

    with pytest.raises(LookupError, match="Missing"):
        find_audio_device("Missing")


def test_audio_device_lookup_handles_missing_dependency(monkeypatch) -> None:
    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "sounddevice":
            raise ModuleNotFoundError(name)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(AudioDeviceCheckUnavailable):
        list_audio_device_names()

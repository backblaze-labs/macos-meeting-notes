"""Static contracts for ScreenCaptureKit microphone routing."""

from __future__ import annotations

from pathlib import Path


NATIVE = Path(__file__).resolve().parents[1] / "src" / "meeting_memory" / "repo" / "native"


def test_native_capture_uses_screencapturekit_default_microphone_route() -> None:
    source = (NATIVE / "ScreenCaptureRecorder.swift").read_text(encoding="utf-8")

    assert "configuration.captureMicrophone = includeMicrophone" in source
    assert "microphoneCaptureDeviceID" not in source


def test_native_capture_refreshes_the_default_microphone_after_device_change() -> None:
    recorder = (NATIVE / "ScreenCaptureRecorder.swift").read_text(encoding="utf-8")
    monitor = (NATIVE / "DefaultInputMonitor.swift").read_text(encoding="utf-8")

    assert "DefaultInputMonitor" in recorder
    assert "stream.updateConfiguration(streamConfiguration())" in recorder
    assert '"event": "microphone-route-refresh-failed"' in recorder
    assert "kAudioHardwarePropertyDefaultInputDevice" in monitor

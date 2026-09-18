"""Default audio-route changes remain visible and recoverable."""

from __future__ import annotations

from pathlib import Path

from meeting_memory.repo.native_audio_health import MAX_ROUTE_CHANGES, HelperStatus


def test_native_capture_observes_and_refreshes_audio_routes() -> None:
    source_root = (
        Path(__file__).resolve().parents[1] / "src" / "meeting_memory" / "repo" / "native"
    )
    recorder = (source_root / "ScreenCaptureRecorder.swift").read_text(encoding="utf-8")
    monitor = (source_root / "AudioRouteMonitor.swift").read_text(encoding="utf-8")

    assert "kAudioHardwarePropertyDefaultInputDevice" in monitor
    assert "kAudioHardwarePropertyDefaultOutputDevice" in monitor
    assert "audio_route_changed" in monitor
    assert "stream.updateConfiguration(streamConfiguration)" in recorder


def test_audio_route_change_warns_immediately_and_is_retained_in_final_diagnostics() -> None:
    status = HelperStatus()
    status.observe(
        {
            "event": "audio_route_changed",
            "elapsed_seconds": 42.5,
            "input_device": "MacBook Pro Microphone",
            "output_device": "AirPods",
        }
    )
    status.observe(
        {
            "event": "stopped",
            "mode": "full-meeting",
            "microphone": "MacBook Pro Microphone",
            "elapsed_seconds": 50,
            "sources": {
                "system": {
                    "callbacks": 1,
                    "frames": 1_600,
                    "peak": 0.2,
                    "discarded_frames": 0,
                    "first_callback_seconds": 0,
                    "last_callback_seconds": 50,
                },
                "microphone": {
                    "callbacks": 1,
                    "frames": 1_600,
                    "peak": 0.3,
                    "discarded_frames": 0,
                    "first_callback_seconds": 0,
                    "last_callback_seconds": 50,
                },
            },
        }
    )

    warning = status.next_warning()
    diagnostics = status.final_diagnostics()
    assert warning is not None
    assert warning.code == "audio_route_changed"
    assert "AirPods" in warning.message
    assert diagnostics is not None
    assert diagnostics.warning_history == ("audio_route_changed",)
    assert diagnostics.route_changes[0].output_device == "AirPods"


def test_audio_route_history_is_bounded() -> None:
    status = HelperStatus()
    for offset in range(MAX_ROUTE_CHANGES + 1):
        status.observe(
            {
                "event": "audio_route_changed",
                "elapsed_seconds": offset,
                "input_device": "MacBook Pro Microphone",
                "output_device": f"AirPods {offset}",
            }
        )
    status.observe(
        {
            "event": "stopped",
            "mode": "full-meeting",
            "microphone": "MacBook Pro Microphone",
            "elapsed_seconds": 50,
            "sources": {
                "system": {
                    "callbacks": 1,
                    "frames": 1_600,
                    "peak": 0.2,
                    "discarded_frames": 0,
                },
                "microphone": {
                    "callbacks": 1,
                    "frames": 1_600,
                    "peak": 0.3,
                    "discarded_frames": 0,
                },
            },
        }
    )

    diagnostics = status.final_diagnostics()
    assert diagnostics is not None
    assert len(diagnostics.route_changes) == MAX_ROUTE_CHANGES

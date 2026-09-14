"""Regression coverage for microphone recovery after a device switch."""

from __future__ import annotations

from meeting_memory.repo.native_audio_health import HelperStatus


def test_microphone_route_refresh_failure_warns_and_is_retained() -> None:
    status = HelperStatus()
    status.observe(
        {
            "event": "microphone-route-refresh-failed",
            "message": "Could not refresh microphone routing: unavailable",
        }
    )

    warning = status.next_warning()
    assert warning is not None
    assert warning.code == "microphone_route_refresh_failed"
    assert "restart this recording" in warning.message

    status.observe(
        {
            "event": "stopped",
            "mode": "full-meeting",
            "microphone": "AirPods",
            "elapsed_seconds": 100,
            "sources": {
                name: {
                    "callbacks": 10,
                    "frames": 16_000,
                    "peak": 0.2,
                    "discarded_frames": 0,
                    "largest_discarded_run": 0,
                    "first_callback_seconds": 0,
                    "last_callback_seconds": 100,
                }
                for name in ("system", "microphone")
            },
        }
    )

    diagnostics = status.final_diagnostics()
    assert diagnostics is not None
    assert "microphone_route_refresh_failed" in diagnostics.warning_history

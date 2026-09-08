"""Tests for the screencapture adapter."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from meeting_memory.repo.screen_capture import ScreenCaptureError, capture_screen


def test_capture_screen_invokes_screencapture_silently(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    destination = tmp_path / "shot.png"

    def runner(args, **kwargs):
        calls.append(args)
        assert kwargs["timeout"] == 30
        destination.write_bytes(b"png")
        return subprocess.CompletedProcess(args, 0, b"", b"")

    capture_screen(destination, runner=runner)

    assert calls == [["/usr/sbin/screencapture", "-x", "-t", "png", str(destination)]]


def test_capture_screen_reports_failures(tmp_path: Path) -> None:
    destination = tmp_path / "shot.png"

    def failing(args, **kwargs):
        return subprocess.CompletedProcess(args, 1, b"", b"could not create image")

    def silent(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, b"", b"")

    def crashing(args, **kwargs):
        raise FileNotFoundError("screencapture")

    with pytest.raises(ScreenCaptureError, match="could not create image"):
        capture_screen(destination, runner=failing)
    with pytest.raises(ScreenCaptureError, match="no image"):
        capture_screen(destination, runner=silent)
    with pytest.raises(ScreenCaptureError, match="could not run"):
        capture_screen(destination, runner=crashing)

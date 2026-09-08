"""macOS screen capture adapter."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

Runner = Callable[..., subprocess.CompletedProcess]
SCREENCAPTURE = "/usr/sbin/screencapture"
CAPTURE_TIMEOUT_SECONDS = 30


class ScreenCaptureError(RuntimeError):
    """The screen could not be captured into the requested file."""


def capture_screen(destination: Path, *, runner: Runner = subprocess.run) -> None:
    """Silently capture the main display as a PNG at ``destination``.

    ``-x`` suppresses the shutter sound; the tray reports success itself. When
    macOS Screen Recording permission is missing, ``screencapture`` still exits
    successfully but only shows the desktop, so the tray documents the
    permission rather than probing for it.
    """

    try:
        completed = runner(
            [SCREENCAPTURE, "-x", "-t", "png", str(destination)],
            check=False,
            capture_output=True,
            timeout=CAPTURE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ScreenCaptureError(f"screencapture could not run: {exc}") from exc
    if completed.returncode != 0:
        stderr = completed.stderr or b""
        detail = stderr.decode("utf-8", "replace").strip()
        raise ScreenCaptureError(detail or f"screencapture exited with {completed.returncode}")
    if not destination.is_file() or destination.stat().st_size == 0:
        raise ScreenCaptureError("screencapture produced no image")

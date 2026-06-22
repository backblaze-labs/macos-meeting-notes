"""Native prompt for naming ad-hoc recordings."""

from __future__ import annotations

from typing import Any


def ask_recording_title(rumps_module: Any, *, default_title: str = "Untitled") -> str | None:
    window = rumps_module.Window(
        message="Name this recording.",
        title="Meeting Title",
        default_text=default_title,
        ok="Save",
        cancel="Cancel",
    )
    response = window.run()
    if not response.clicked:
        return None
    return response.text.strip() or default_title

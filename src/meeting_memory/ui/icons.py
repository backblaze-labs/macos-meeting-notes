"""Status-bar icon helpers."""

from __future__ import annotations

from importlib.resources import files


def tray_icon_path() -> str:
    return str(files("meeting_memory.ui.assets").joinpath("robot-template.png"))

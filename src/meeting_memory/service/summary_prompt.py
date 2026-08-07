"""Local storage for the configurable notes-generation prompt."""

from __future__ import annotations

from pathlib import Path

from meeting_memory.config.defaults import (
    DEFAULT_SUMMARY_PROMPT_FILE,
    DEFAULT_SUMMARY_PROMPT_TEMPLATE,
)
from meeting_memory.config.settings import Settings


def summary_prompt_path(settings: Settings) -> Path:
    return settings.summary_prompt_path or Path(DEFAULT_SUMMARY_PROMPT_FILE)


def read_summary_prompt(settings: Settings) -> str:
    path = summary_prompt_path(settings)
    if path.exists():
        return path.read_text(encoding="utf-8")
    return DEFAULT_SUMMARY_PROMPT_TEMPLATE


def write_summary_prompt(settings: Settings, prompt: str) -> Path:
    content = prompt.strip()
    if not content:
        raise ValueError("The notes prompt cannot be empty.")

    path = summary_prompt_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{content}\n", encoding="utf-8")
    return path

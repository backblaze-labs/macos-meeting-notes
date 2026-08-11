"""Local storage for the configurable notes-generation prompt."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from meeting_memory.config.defaults import (
    DEFAULT_SUMMARY_PROMPT_FILE,
    DEFAULT_SUMMARY_PROMPT_TEMPLATE,
)
from meeting_memory.config.settings import Settings
from meeting_memory.repo.prompt_source import MAX_PROMPT_BYTES, read_prompt_text
from meeting_memory.service.atomic_io import atomic_replace_text_at
from meeting_memory.service.pinned_fs import open_directory_tree

MAX_SUMMARY_PROMPT_BYTES = MAX_PROMPT_BYTES


def summary_prompt_path(settings: Settings) -> Path:
    return settings.summary_prompt_path or Path(DEFAULT_SUMMARY_PROMPT_FILE)


def read_summary_prompt(settings: Settings) -> str:
    return read_prompt_text(summary_prompt_path(settings)) or DEFAULT_SUMMARY_PROMPT_TEMPLATE


def write_summary_prompt(settings: Settings, prompt: str) -> Path:
    content = prompt.strip()
    if not content:
        raise ValueError("The notes prompt cannot be empty.")
    encoded = f"{content}\n".encode()
    if len(encoded) > MAX_SUMMARY_PROMPT_BYTES:
        raise ValueError("The notes prompt exceeds the supported size.")

    path = summary_prompt_path(settings)
    directory_fd = open_directory_tree(path.parent, create=True)
    try:
        try:
            existing = os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            existing = None
        if existing is not None and not stat.S_ISREG(existing.st_mode):
            raise OSError("notes prompt destination must be a regular file")
        atomic_replace_text_at(directory_fd, path.name, encoded.decode("utf-8"))
        return path
    finally:
        os.close(directory_fd)

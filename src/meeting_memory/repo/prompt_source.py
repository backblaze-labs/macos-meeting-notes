"""Bounded stable reads for the prompt used in external Notes requests."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from meeting_memory.repo.pinned_path import open_parent_directory

MAX_PROMPT_BYTES = 1_048_576


def read_prompt_text(path: Path) -> str | None:
    """Return a stable prompt snapshot, or None only when the file is missing."""

    try:
        directory_fd = open_parent_directory(path)
    except FileNotFoundError:
        return None
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
    try:
        try:
            descriptor = os.open(path.name, flags, dir_fd=directory_fd)
        except FileNotFoundError:
            return None
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_PROMPT_BYTES:
                raise OSError("notes prompt must be a bounded regular file")
            content = _read_bounded(descriptor)
            after = os.fstat(descriptor)
            if _identity(before) != _identity(after):
                raise OSError("notes prompt changed while being read")
            return content.decode("utf-8")
        finally:
            os.close(descriptor)
    finally:
        os.close(directory_fd)


def _read_bounded(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    remaining = MAX_PROMPT_BYTES + 1
    while remaining:
        chunk = os.read(descriptor, min(65_536, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    content = b"".join(chunks)
    if len(content) > MAX_PROMPT_BYTES:
        raise OSError("notes prompt exceeds the supported size")
    return content


def _identity(info) -> tuple[int, ...]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns

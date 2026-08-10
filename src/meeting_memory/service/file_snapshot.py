"""Stable no-follow reads for local artifact text snapshots."""

from __future__ import annotations

import os
import stat
from pathlib import Path


def read_regular_text_snapshot(path: Path) -> str:
    """Open once, reject non-regular sources, and read only from that descriptor."""

    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    descriptor = os.open(path, flags)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError(f"artifact is not a regular file: {path}")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        return b"".join(chunks).decode("utf-8")
    finally:
        os.close(descriptor)

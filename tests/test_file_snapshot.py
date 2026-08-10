"""Stable no-follow text snapshot tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from meeting_memory.service.file_snapshot import read_regular_text_snapshot


def test_snapshot_rejects_symlink_and_fifo(tmp_path: Path) -> None:
    target = tmp_path / "target.md"
    target.write_text("private", encoding="utf-8")
    link = tmp_path / "link.md"
    link.symlink_to(target)
    fifo = tmp_path / "notes.pipe"
    os.mkfifo(fifo)

    with pytest.raises(OSError):
        read_regular_text_snapshot(link)
    with pytest.raises(ValueError, match="regular file"):
        read_regular_text_snapshot(fifo)


def test_snapshot_never_reopens_path_after_descriptor_is_pinned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "notes.md"
    moved = tmp_path / "original.md"
    path.write_text("original snapshot", encoding="utf-8")
    original_read = os.read
    swapped = False

    def swap_path_then_read(descriptor: int, size: int) -> bytes:
        nonlocal swapped
        if not swapped:
            swapped = True
            path.rename(moved)
            path.write_text("replacement secret", encoding="utf-8")
        return original_read(descriptor, size)

    monkeypatch.setattr(os, "read", swap_path_then_read)

    assert read_regular_text_snapshot(path) == "original snapshot"
    assert path.read_text(encoding="utf-8") == "replacement secret"

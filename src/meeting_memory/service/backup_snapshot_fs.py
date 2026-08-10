"""Pinned private-directory filesystem mechanics for Backup snapshots."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from meeting_memory.service.pinned_fs import (
    create_private_child,
    open_directory_tree,
    same_open_directory,
)

SNAPSHOT_FILENAMES = ("recording.m4a", "transcript.md", "transcript.normalized.md")


@dataclass(frozen=True)
class CapturedSnapshotFiles:
    directory: Path
    audio_path: Path
    transcript_path: Path
    normalized_path: Path
    directory_device: int
    directory_inode: int


def create_snapshot_files(
    parent: Path,
    audio_fd: int,
    transcript: bytes,
    normalized: bytes,
) -> CapturedSnapshotFiles:
    parent_fd = open_directory_tree(parent, create=True, require_private_final=True)
    child_name, child_fd = create_private_child(parent_fd, "backup.")
    directory = parent / child_name
    try:
        _copy_fd_at(audio_fd, child_fd, "recording.m4a")
        _write_bytes_at(child_fd, "transcript.md", transcript)
        _write_bytes_at(child_fd, "transcript.normalized.md", normalized)
        os.fsync(child_fd)
        if not same_open_directory(directory, child_fd):
            raise ValueError("backup snapshot directory changed during capture")
        info = os.fstat(child_fd)
        return CapturedSnapshotFiles(
            directory,
            directory / "recording.m4a",
            directory / "transcript.md",
            directory / "transcript.normalized.md",
            info.st_dev,
            info.st_ino,
        )
    except BaseException:
        _cleanup_child_at(parent_fd, child_fd, child_name)
        raise
    finally:
        os.close(child_fd)
        os.close(parent_fd)


def cleanup_snapshot_directory(directory: Path, device: int, inode: int) -> None:
    """Idempotently remove only the exact captured directory, never a replacement."""

    try:
        parent_fd = open_directory_tree(directory.parent)
    except FileNotFoundError:
        return
    child_fd = -1
    try:
        try:
            child_fd = os.open(
                directory.name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=parent_fd,
            )
        except FileNotFoundError:
            return
        info = os.fstat(child_fd)
        if (info.st_dev, info.st_ino) != (device, inode):
            raise ValueError("backup snapshot directory was replaced before cleanup")
        _cleanup_child_at(parent_fd, child_fd, directory.name)
    finally:
        if child_fd >= 0:
            os.close(child_fd)
        os.close(parent_fd)


def _copy_fd_at(source_fd: int, directory_fd: int, filename: str) -> None:
    os.lseek(source_fd, 0, os.SEEK_SET)
    descriptor = _create_file_at(directory_fd, filename)
    with os.fdopen(descriptor, "wb") as writer:
        while chunk := os.read(source_fd, 1024 * 1024):
            writer.write(chunk)
        writer.flush()
        os.fsync(writer.fileno())


def _write_bytes_at(directory_fd: int, filename: str, content: bytes) -> None:
    descriptor = _create_file_at(directory_fd, filename)
    with os.fdopen(descriptor, "wb") as writer:
        writer.write(content)
        writer.flush()
        os.fsync(writer.fileno())


def _create_file_at(directory_fd: int, filename: str) -> int:
    return os.open(
        filename,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
        dir_fd=directory_fd,
    )


def _cleanup_child_at(parent_fd: int, child_fd: int, child_name: str) -> None:
    for filename in SNAPSHOT_FILENAMES:
        try:
            info = os.stat(filename, dir_fd=child_fd, follow_symlinks=False)
            if stat.S_ISREG(info.st_mode):
                os.unlink(filename, dir_fd=child_fd)
        except FileNotFoundError:
            pass
    os.fsync(child_fd)
    os.rmdir(child_name, dir_fd=parent_fd)
    os.fsync(parent_fd)

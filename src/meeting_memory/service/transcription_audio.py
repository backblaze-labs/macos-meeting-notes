"""Stable private audio snapshots for optional Transcription egress."""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

from meeting_memory.service.meeting_document import (
    open_meeting_document,
    require_meeting_directory_identity,
)
from meeting_memory.types.meeting import MeetingDirectoryIdentity, MeetingFiles


@contextmanager
def capture_transcription_audio(
    meetings_dir: Path,
    files: MeetingFiles,
    *,
    expected_directory_identity: MeetingDirectoryIdentity | None = None,
) -> Iterator[BinaryIO]:
    """Yield an unlinked read-only copy from one pinned owned meeting."""

    if files.audio_path != files.directory / "recording.m4a":
        raise ValueError("Transcription audio must be the canonical meeting recording")
    with open_meeting_document(meetings_dir, files.directory) as document:
        require_meeting_directory_identity(document, expected_directory_identity)
        source_fd = _open_regular_audio(document.directory_fd)
        try:
            reader = private_stable_copy(source_fd)
        finally:
            os.close(source_fd)
    try:
        yield reader
    finally:
        reader.close()


def _open_regular_audio(directory_fd: int) -> int:
    descriptor = os.open(
        "recording.m4a",
        os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
        dir_fd=directory_fd,
    )
    try:
        opened = os.fstat(descriptor)
        visible = os.stat(
            "recording.m4a",
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_size <= 0
            or (opened.st_dev, opened.st_ino) != (visible.st_dev, visible.st_ino)
        ):
            raise ValueError("Transcription audio must be a stable non-empty regular file")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def private_stable_copy(source_fd: int) -> BinaryIO:
    """Return an anonymous read-only copy that matches one stable source view."""

    descriptor, raw_path = tempfile.mkstemp(prefix="meeting-memory-transcription.")
    path = Path(raw_path)
    created = os.fstat(descriptor)
    identity: tuple[int, int] | None = (created.st_dev, created.st_ino)
    reader_fd = -1
    try:
        source_info = os.fstat(source_fd)
        source_before = _sha256(source_fd, source_info.st_size)
        copied = hashlib.sha256()
        offset = 0
        with os.fdopen(descriptor, "wb") as writer:
            while offset < source_info.st_size:
                chunk = os.pread(
                    source_fd,
                    min(1024 * 1024, source_info.st_size - offset),
                    offset,
                )
                if not chunk:
                    raise ValueError("Source changed during private snapshot")
                writer.write(chunk)
                copied.update(chunk)
                offset += len(chunk)
            writer.flush()
            os.fsync(writer.fileno())
            created = os.fstat(writer.fileno())
            identity = (created.st_dev, created.st_ino)
        if copied.hexdigest() != source_before or _sha256(
            source_fd,
            source_info.st_size,
        ) != source_before:
            raise ValueError("Source changed during private snapshot")
        reader_fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        opened = os.fstat(reader_fd)
        visible = path.stat(follow_symlinks=False)
        if identity != (opened.st_dev, opened.st_ino) or identity != (
            visible.st_dev,
            visible.st_ino,
        ):
            raise ValueError("Private snapshot changed before unlink")
        path.unlink()
        reader = os.fdopen(reader_fd, "rb")
        # Ownership moved to reader; the exception path must not close it again.
        reader_fd = -1
        return reader
    except BaseException:
        if reader_fd >= 0:
            os.close(reader_fd)
        _unlink_same_temp(path, identity)
        raise


def _sha256(descriptor: int, size: int) -> str:
    digest = hashlib.sha256()
    for offset in range(0, size, 1024 * 1024):
        chunk = os.pread(descriptor, min(1024 * 1024, size - offset), offset)
        if not chunk:
            break
        digest.update(chunk)
    return digest.hexdigest()


def _unlink_same_temp(path: Path, identity: tuple[int, int] | None) -> None:
    try:
        visible = path.stat(follow_symlinks=False)
    except FileNotFoundError:
        return
    if identity == (visible.st_dev, visible.st_ino):
        path.unlink()

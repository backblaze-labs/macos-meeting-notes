"""No-follow validation and pinned streams for one Backup snapshot request."""

from __future__ import annotations

import os
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from meeting_memory.types.artifacts import BackupSnapshotUpload
from meeting_memory.types.backup import backup_revision_stream, owned_backup_transcript_slug


@dataclass
class VerifiedBackupSnapshot:
    audio: BinaryIO
    transcript: BinaryIO


@contextmanager
def open_verified_backup_snapshot(
    request: BackupSnapshotUpload,
) -> Iterator[VerifiedBackupSnapshot]:
    """Pin both regular files and verify the claimed directory/revision."""

    directory_fd = _open_directory_tree(request.directory)
    audio_fd = transcript_fd = -1
    private_audio: BinaryIO
    private_transcript: BinaryIO
    try:
        directory_info = os.fstat(directory_fd)
        if (directory_info.st_dev, directory_info.st_ino) != (
            request.directory_device,
            request.directory_inode,
        ):
            raise ValueError("backup snapshot directory identity does not match request")
        audio_fd = _open_regular_at(directory_fd, "recording.m4a")
        transcript_fd = _open_regular_at(directory_fd, "transcript.md")
        private_audio = _private_copy(audio_fd)
        try:
            private_transcript = _private_copy(transcript_fd)
        except BaseException:
            private_audio.close()
            raise
    finally:
        if audio_fd >= 0:
            os.close(audio_fd)
        if transcript_fd >= 0:
            os.close(transcript_fd)
        os.close(directory_fd)
    try:
        if (
            _revision(private_audio, private_transcript, request.meeting_slug)
            != request.revision
        ):
            raise ValueError("backup snapshot bytes do not match the claimed revision")
        yield VerifiedBackupSnapshot(private_audio, private_transcript)
    except BaseException:
        _close_private_handles(private_audio, private_transcript, suppress=True)
        raise
    else:
        _close_private_handles(private_audio, private_transcript, suppress=False)


def _open_directory_tree(path: Path) -> int:
    absolute = path if path.is_absolute() else Path.cwd() / path
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in absolute.parts[1:]:
            child = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _open_regular_at(directory_fd: int, filename: str) -> int:
    descriptor = os.open(
        filename,
        os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
        dir_fd=directory_fd,
    )
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise ValueError(f"backup snapshot source is not regular: {filename}")
    return descriptor


def _private_copy(source_fd: int) -> BinaryIO:
    """Copy into an unlinked read-only handle with no surviving writer."""

    descriptor, raw_path = tempfile.mkstemp(prefix="meeting-memory-b2.")
    path = Path(raw_path)
    created = os.fstat(descriptor)
    identity: tuple[int, int] | None = (created.st_dev, created.st_ino)
    reader_fd = -1
    offset = 0
    try:
        with os.fdopen(descriptor, "wb") as writer:
            while chunk := os.pread(source_fd, 1024 * 1024, offset):
                writer.write(chunk)
                offset += len(chunk)
            writer.flush()
            os.fsync(writer.fileno())
            info = os.fstat(writer.fileno())
            identity = (info.st_dev, info.st_ino)
        reader_fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        opened = os.fstat(reader_fd)
        visible = path.stat(follow_symlinks=False)
        if identity != (opened.st_dev, opened.st_ino) or identity != (
            visible.st_dev,
            visible.st_ino,
        ):
            raise ValueError("private backup handle changed before unlink")
        path.unlink()
        stream = os.fdopen(reader_fd, "rb")
        reader_fd = -1
        return stream
    except BaseException:
        if reader_fd >= 0:
            os.close(reader_fd)
        _unlink_same_temp(path, identity)
        raise


def _unlink_same_temp(path: Path, identity: tuple[int, int] | None) -> None:
    try:
        visible = path.stat(follow_symlinks=False)
    except FileNotFoundError:
        return
    if identity == (visible.st_dev, visible.st_ino):
        path.unlink()


def _close_private_handles(
    audio: BinaryIO,
    transcript: BinaryIO,
    *,
    suppress: bool,
) -> None:
    first_error: Exception | None = None
    for stream in (audio, transcript):
        try:
            stream.close()
        except Exception as exc:
            first_error = first_error or exc
    if first_error is not None and not suppress:
        raise first_error


def _revision(audio: BinaryIO, transcript: BinaryIO, request_slug: str) -> str:
    transcript.seek(0)
    transcript_bytes = transcript.read()
    transcript.seek(0)
    slug = owned_backup_transcript_slug(transcript_bytes)
    if slug != request_slug:
        raise ValueError("backup snapshot transcript identity does not match request")
    audio.seek(0, os.SEEK_END)
    audio_size = audio.tell()
    return backup_revision_stream(audio, audio_size, transcript_bytes)

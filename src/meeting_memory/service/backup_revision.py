"""Deterministic schema-v2 backup revisions and immutable snapshots."""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from meeting_memory.service.backup_snapshot_fs import (
    cleanup_snapshot_directory,
    create_snapshot_files,
)
from meeting_memory.service.meeting_document import open_meeting_document
from meeting_memory.types.artifacts import BackupSnapshotUpload
from meeting_memory.types.backup import (
    backup_revision_bytes,
    backup_revision_stream,
    normalize_backup_transcript,
    owned_backup_transcript_slug,
)


@dataclass(frozen=True)
class BackupSnapshot:
    """Matching file-backed copies captured for one attempted upload."""

    revision: str
    meeting_slug: str
    audio_path: Path
    transcript_path: Path
    normalized_transcript_path: Path
    directory: Path
    directory_device: int
    directory_inode: int

    def cleanup(self) -> None:
        cleanup_snapshot_directory(
            self.directory,
            self.directory_device,
            self.directory_inode,
        )

    def upload_request(self) -> BackupSnapshotUpload:
        return BackupSnapshotUpload(
            meeting_slug=self.meeting_slug,
            revision=self.revision,
            directory=self.directory,
            directory_device=self.directory_device,
            directory_inode=self.directory_inode,
        )

    def __enter__(self) -> BackupSnapshot:
        return self

    def __exit__(self, exc_type: object, *_args: object) -> None:
        try:
            self.cleanup()
        except Exception:
            if exc_type is None:
                raise


def normalize_transcript_for_backup(transcript: bytes | str) -> bytes:
    """Remove only Backup bookkeeping fields, normalize LF, end in one LF."""

    return normalize_backup_transcript(transcript)


def backup_revision(audio: bytes, transcript: bytes | str) -> str:
    return backup_revision_bytes(audio, transcript)


def compute_backup_revision(audio_path: Path, transcript_path: Path) -> str:
    with _regular_fd(audio_path) as (audio_fd, audio_size):
        with _regular_fd(transcript_path) as (transcript_fd, _):
            transcript = _read_fd(transcript_fd)
        return _revision_from_fd(audio_fd, audio_size, transcript)


def compute_backup_revision_with_transcript(
    audio_path: Path,
    transcript: bytes | str,
) -> str:
    """Hash one audio file against supplied prospective transcript content."""

    with _regular_fd(audio_path) as (audio_fd, audio_size):
        return _revision_from_fd(audio_fd, audio_size, transcript)


def compute_backup_revision_from_audio_fd(
    audio_fd: int,
    transcript: bytes | str,
) -> str:
    """Hash prospective transcript content against one pinned regular audio fd."""

    info = os.fstat(audio_fd)
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("backup audio source is not a regular file")
    return _revision_from_fd(audio_fd, info.st_size, transcript)


def capture_backup_snapshot(
    meeting_dir: Path,
    snapshot_root: Path | None = None,
) -> BackupSnapshot:
    """Copy both artifacts through one pinned owned meeting directory."""

    with open_meeting_document(meeting_dir.parent, meeting_dir) as document:
        audio_fd, audio_size = _regular_at(document.directory_fd, "recording.m4a")
        try:
            transcript = document.text.encode("utf-8")
            if snapshot_root is None:
                meetings_root = document.root_path
                parent = meetings_root / ".meeting-memory-staging" / "backup-snapshots"
            else:
                parent = snapshot_root.expanduser()
            meeting_slug = owned_backup_transcript_slug(transcript)
            normalized = normalize_transcript_for_backup(transcript)
            revision = _revision_from_fd(audio_fd, audio_size, transcript)
            captured = create_snapshot_files(parent, audio_fd, transcript, normalized)
        finally:
            os.close(audio_fd)
    return BackupSnapshot(
        revision=revision,
        meeting_slug=meeting_slug,
        audio_path=captured.audio_path,
        transcript_path=captured.transcript_path,
        normalized_transcript_path=captured.normalized_path,
        directory=captured.directory,
        directory_device=captured.directory_device,
        directory_inode=captured.directory_inode,
    )


@contextmanager
def _regular_fd(path: Path) -> Iterator[tuple[int, int]]:
    """Open without following the final symlink and reject non-regular sources."""

    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    descriptor = os.open(path, flags)
    try:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            raise ValueError(f"backup source is not a regular file: {path}")
        yield descriptor, file_stat.st_size
    finally:
        os.close(descriptor)


def _read_fd(descriptor: int) -> bytes:
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while chunk := os.read(descriptor, 1024 * 1024):
        chunks.append(chunk)
    return b"".join(chunks)


def _regular_at(directory_fd: int, filename: str) -> tuple[int, int]:
    descriptor = os.open(
        filename,
        os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
        dir_fd=directory_fd,
    )
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode):
        os.close(descriptor)
        raise ValueError(f"backup source is not a regular file: {filename}")
    return descriptor, info.st_size


def _copy_fd(descriptor: int, destination: Path) -> None:
    os.lseek(descriptor, 0, os.SEEK_SET)
    with destination.open("xb") as writer:
        while chunk := os.read(descriptor, 1024 * 1024):
            writer.write(chunk)
        writer.flush()
        os.fsync(writer.fileno())


def _revision_from_fd(audio_fd: int, audio_size: int, transcript: bytes | str) -> str:
    with os.fdopen(os.dup(audio_fd), "rb") as stream:
        return backup_revision_stream(stream, audio_size, transcript)

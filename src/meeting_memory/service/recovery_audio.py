"""Verified M4A copy and stable-path WAV conversion primitives."""

from __future__ import annotations

import hashlib
import os
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from meeting_memory.service.atomic_io import copy_audio_from_fd
from meeting_memory.service.pinned_fs import open_directory_tree, same_open_directory
from meeting_memory.types.recovery import RecoveryIndexEntry

RecoveryAudioConverter = Callable[[Path, Path], object]
RecoveryM4AValidator = Callable[[Path], object]
PinnedMaterializer = Callable[[int, Path], None]
OutputValidator = Callable[[Path], None]


def recovery_audio_plan(
    entry: RecoveryIndexEntry,
    source_fd: int,
    converter: RecoveryAudioConverter | None,
    validate_m4a: RecoveryM4AValidator,
) -> tuple[PinnedMaterializer, OutputValidator]:
    """Select verified direct M4A copy or stable-snapshot WAV conversion."""

    if not callable(validate_m4a):
        raise TypeError("recovery requires an M4A validator")
    suffix = entry.source_path.suffix.casefold()
    if suffix == ".m4a":
        return copy_audio_from_fd, lambda path: validate_m4a(path)
    if suffix != ".wav":
        raise ValueError("recovery source must be WAV or M4A")
    _validate_wav_fd(source_fd)
    if converter is None:
        raise ValueError("WAV recovery requires an audio converter")
    if not callable(converter):
        raise TypeError("recovery audio converter must be callable")

    def convert(_source_fd: int, destination: Path) -> None:
        with _stable_wav_snapshot(entry, source_fd) as snapshot:
            snapshot.verify()
            converter(snapshot.path, destination)
            snapshot.verify()

    return convert, lambda path: validate_m4a(path)


@dataclass
class _StableSnapshot:
    path: Path
    directory_fd: int
    descriptor: int
    name: str
    device: int
    inode: int
    size: int
    sha256: str

    def verify(self) -> None:
        opened = os.fstat(self.descriptor)
        visible = os.stat(self.name, dir_fd=self.directory_fd, follow_symlinks=False)
        identity = (self.device, self.inode)
        if (
            identity != (opened.st_dev, opened.st_ino)
            or identity != (visible.st_dev, visible.st_ino)
            or opened.st_size != self.size
            or _sha256_fd(self.descriptor, self.size) != self.sha256
        ):
            raise ValueError("stable WAV conversion source changed")

    def cleanup(self) -> None:
        try:
            self.verify()
            os.unlink(self.name, dir_fd=self.directory_fd)
            os.fsync(self.directory_fd)
        finally:
            os.close(self.descriptor)
            os.close(self.directory_fd)


@contextmanager
def _stable_wav_snapshot(
    entry: RecoveryIndexEntry,
    source_fd: int,
) -> Iterator[_StableSnapshot]:
    directory_fd = open_directory_tree(entry.session_directory)
    if not same_open_directory(entry.session_directory, directory_fd):
        os.close(directory_fd)
        raise ValueError("recovery session changed before WAV conversion")
    name = f".conversion-source.{uuid.uuid4().hex}.wav"
    descriptor = os.open(
        name,
        os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
        dir_fd=directory_fd,
    )
    try:
        snapshot = _copy_verified_snapshot(entry, source_fd, directory_fd, descriptor, name)
    except BaseException:
        os.close(descriptor)
        try:
            os.unlink(name, dir_fd=directory_fd)
        except FileNotFoundError:
            # Snapshot creation may fail before the temporary name is visible.
            pass
        os.close(directory_fd)
        raise
    try:
        yield snapshot
    except BaseException:
        try:
            snapshot.cleanup()
        except Exception:
            # Cleanup must not hide the original conversion or validation error.
            pass
        raise
    else:
        snapshot.cleanup()


def _copy_verified_snapshot(
    entry: RecoveryIndexEntry,
    source_fd: int,
    directory_fd: int,
    descriptor: int,
    name: str,
) -> _StableSnapshot:
    expected_size, expected_hash = _expected_bytes(entry)
    digest = hashlib.sha256()
    offset = 0
    while chunk := os.pread(source_fd, 1024 * 1024, offset):
        _write_all(descriptor, chunk)
        digest.update(chunk)
        offset += len(chunk)
    os.fsync(descriptor)
    if offset != expected_size or digest.hexdigest() != expected_hash:
        raise ValueError("recovery source changed during WAV snapshot")
    info = os.fstat(descriptor)
    return _StableSnapshot(
        entry.session_directory / name,
        directory_fd,
        descriptor,
        name,
        info.st_dev,
        info.st_ino,
        expected_size,
        expected_hash,
    )


def _validate_wav_fd(descriptor: int) -> None:
    header = os.pread(descriptor, 12, 0)
    if len(header) < 12 or header[:4] != b"RIFF" or header[8:12] != b"WAVE":
        raise ValueError("recovery WAV source has an invalid RIFF/WAVE header")


def _expected_bytes(entry: RecoveryIndexEntry) -> tuple[int, str]:
    if entry.source_size is None or entry.source_sha256 is None:
        raise ValueError("recovery source bytes must be pinned")
    return entry.source_size, entry.source_sha256


def _sha256_fd(descriptor: int, size: int) -> str:
    digest = hashlib.sha256()
    offset = 0
    while offset < size:
        chunk = os.pread(descriptor, min(1024 * 1024, size - offset), offset)
        if not chunk:
            break
        digest.update(chunk)
        offset += len(chunk)
    return digest.hexdigest()


def _write_all(descriptor: int, content: bytes) -> None:
    offset = 0
    while offset < len(content):
        offset += os.write(descriptor, content[offset:])

"""Pinned no-follow filesystem primitives for the private preference store."""

from __future__ import annotations

import fcntl
import os
import stat
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path

from meeting_memory.service.pinned_fs import open_directory_tree

MAX_PREFERENCES_BYTES = 1_048_576
DIRECTORY_MODE = 0o700
FILE_MODE = 0o600
LOCK_FILENAME = ".preferences.lock"
LOCK_OPEN_ATTEMPTS = 4
_WRITER_LOCK = threading.Lock()


class DirectorySyncUncertain(OSError):
    """A replacement is visible, but its directory entry did not flush."""


def read_document(path: Path) -> bytes | None:
    """Read a private regular document through a pinned directory."""

    filename = _filename(path)
    try:
        directory_fd = open_directory_tree(
            path.parent,
            require_private_final=True,
        )
    except FileNotFoundError:
        return None
    try:
        _validate_private_directory(directory_fd)
        return read_document_at(directory_fd, filename)
    finally:
        os.close(directory_fd)


@contextmanager
def locked_directory(path: Path):
    """Pin private storage and serialize every writer through one lock file."""

    with _WRITER_LOCK:
        filename = _filename(path)
        directory_fd = open_directory_tree(
            path.parent,
            create=True,
            require_private_final=True,
        )
        lock_fd = -1
        try:
            _validate_private_directory(directory_fd)
            lock_exists = _entry_exists(directory_fd, LOCK_FILENAME)
            lock_fd = _open_lock_file(directory_fd)
            _validate_private_file(lock_fd)
            if not lock_exists:
                _sync_directory(directory_fd)
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            yield directory_fd, filename
        finally:
            if lock_fd >= 0:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                finally:
                    os.close(lock_fd)
            os.close(directory_fd)


def read_document_at(directory_fd: int, filename: str) -> bytes | None:
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(filename, flags, dir_fd=directory_fd)
    except FileNotFoundError:
        return None
    try:
        info = _validate_private_file(descriptor)
        if info.st_size > MAX_PREFERENCES_BYTES:
            raise ValueError("preference document is too large")
        chunks: list[bytes] = []
        remaining = MAX_PREFERENCES_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        if len(content) > MAX_PREFERENCES_BYTES:
            raise ValueError("preference document is too large")
        return content
    finally:
        os.close(descriptor)


def replace_document_at(directory_fd: int, filename: str, content: bytes) -> None:
    """Atomically and durably replace one private direct-child document."""

    _validate_existing_target(directory_fd, filename)
    temporary = f".{filename}.{uuid.uuid4().hex}"
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        FILE_MODE,
        dir_fd=directory_fd,
    )
    replaced = False
    try:
        _write_all(descriptor, content)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(
            temporary,
            filename,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        replaced = True
        try:
            _sync_directory(directory_fd)
        except OSError:
            raise DirectorySyncUncertain(
                "preference replacement directory sync failed"
            ) from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if not replaced:
            try:
                os.unlink(temporary, dir_fd=directory_fd)
            except FileNotFoundError:
                pass


def _write_all(descriptor: int, content: bytes) -> None:
    offset = 0
    while offset < len(content):
        written = os.write(descriptor, content[offset:])
        if written <= 0:
            raise OSError("preference write did not make progress")
        offset += written


def _validate_private_directory(descriptor: int) -> None:
    info = os.fstat(descriptor)
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != DIRECTORY_MODE
    ):
        raise ValueError("preference directory is not private app storage")


def _validate_private_file(descriptor: int):
    info = os.fstat(descriptor)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != FILE_MODE
    ):
        raise ValueError("preference entry is not a private owned regular file")
    return info


def _validate_existing_target(directory_fd: int, filename: str) -> None:
    try:
        info = os.stat(filename, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != FILE_MODE
    ):
        raise ValueError("preference target is not a private owned regular file")


def _entry_exists(directory_fd: int, filename: str) -> bool:
    try:
        os.stat(filename, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return True


def _open_lock_file(directory_fd: int) -> int:
    for attempt in range(LOCK_OPEN_ATTEMPTS):
        try:
            return os.open(
                LOCK_FILENAME,
                os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
                FILE_MODE,
                dir_fd=directory_fd,
            )
        except FileNotFoundError:
            if attempt == LOCK_OPEN_ATTEMPTS - 1:
                raise
    raise OSError("preference writer lock could not be opened")


def _sync_directory(directory_fd: int) -> None:
    os.fsync(directory_fd)


def _filename(path: Path) -> str:
    if path.name in {"", ".", ".."}:
        raise ValueError("preference path requires a direct-child filename")
    return path.name

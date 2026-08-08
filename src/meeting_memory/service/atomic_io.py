"""Durable filesystem primitives for local meeting artifacts."""

from __future__ import annotations

import ctypes
import errno
import os
import sys
import tempfile
from pathlib import Path

RENAME_EXCL = 0x00000004


def fsync_directory(path: Path) -> None:
    """Flush directory entries to the filesystem."""

    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def fsync_file(path: Path) -> None:
    """Flush a closed, readable file without changing its content."""

    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_text_durable(path: Path, text: str, *, exclusive: bool = False) -> None:
    mode = "x" if exclusive else "w"
    with path.open(mode, encoding="utf-8", newline="\n") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())


def atomic_replace_text(path: Path, text: str) -> None:
    """Replace one text file atomically and durably on its filesystem."""

    descriptor, raw_temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(raw_temp)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
        fsync_directory(path.parent)
    except BaseException:
        if temp_path.exists():
            temp_path.unlink()
        raise


def rename_directory_no_replace(source: Path, destination: Path) -> None:
    """Atomically publish a directory without ever replacing a destination."""

    if sys.platform != "darwin":
        raise RuntimeError("atomic no-clobber directory publication requires macOS")
    libc = ctypes.CDLL(None, use_errno=True)
    renamex = libc.renamex_np
    renamex.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
    renamex.restype = ctypes.c_int
    result = renamex(os.fsencode(source), os.fsencode(destination), RENAME_EXCL)
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
        raise FileExistsError(error_number, os.strerror(error_number), destination)
    raise OSError(error_number, os.strerror(error_number), destination)


def copy_audio(source: Path, destination: Path) -> None:
    """Copy source audio into a newly-created destination and flush it."""

    with source.open("rb") as reader, destination.open("xb") as writer:
        while chunk := reader.read(1024 * 1024):
            writer.write(chunk)
        writer.flush()
        os.fsync(writer.fileno())

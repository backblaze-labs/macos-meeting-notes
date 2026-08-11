"""Component-wise no-follow directory access for private staging trees."""

from __future__ import annotations

import os
import stat
import uuid
from pathlib import Path


def open_directory_tree(
    path: Path,
    *,
    create: bool = False,
    require_private_final: bool = False,
) -> int:
    """Open each component with O_NOFOLLOW and optionally create private gaps."""

    absolute = path.expanduser()
    if not absolute.is_absolute():
        raise ValueError("pinned filesystem paths must be absolute")
    if require_private_final and absolute == Path("/"):
        raise ValueError("filesystem root cannot be used as private staging")
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for index, part in enumerate(absolute.parts[1:], start=1):
            try:
                child = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=descriptor,
                )
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(part, 0o700, dir_fd=descriptor)
                except FileExistsError:
                    # A concurrent creator won; the no-follow open below validates it.
                    pass
                os.fsync(descriptor)
                child = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=descriptor,
                )
            os.close(descriptor)
            descriptor = child
            is_final = index == len(absolute.parts) - 1
            if is_final and require_private_final:
                mode = stat.S_IMODE(os.fstat(descriptor).st_mode)
                if mode & 0o077:
                    raise ValueError("private staging directory has unsafe permissions")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def same_open_directory(path: Path, descriptor: int) -> bool:
    """Compare a visible directory entry with an already pinned descriptor."""

    try:
        observed = path.stat(follow_symlinks=False)
    except OSError:
        return False
    expected = os.fstat(descriptor)
    return stat.S_ISDIR(observed.st_mode) and (
        expected.st_dev,
        expected.st_ino,
    ) == (observed.st_dev, observed.st_ino)


def create_private_child(parent_fd: int, prefix: str) -> tuple[str, int]:
    for _attempt in range(20):
        name = f"{prefix}{uuid.uuid4().hex}"
        try:
            os.mkdir(name, 0o700, dir_fd=parent_fd)
        except FileExistsError:
            continue
        descriptor = os.open(
            name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=parent_fd,
        )
        os.fsync(parent_fd)
        return name, descriptor
    raise FileExistsError("could not allocate a unique private directory")


def read_regular_text_at(directory_fd: int, filename: str) -> str:
    descriptor = os.open(
        filename,
        os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
        dir_fd=directory_fd,
    )
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError(f"artifact is not a regular file: {filename}")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        return b"".join(chunks).decode("utf-8")
    finally:
        os.close(descriptor)

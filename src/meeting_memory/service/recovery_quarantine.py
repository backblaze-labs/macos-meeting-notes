"""Identity-bound quarantine for a rejected recovery publication."""

from __future__ import annotations

import os
import stat
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from meeting_memory.service.pinned_fs import open_directory_tree
from meeting_memory.service.recovery_marker import require_recovery_marker_directory
from meeting_memory.types.meeting import validate_meeting_slug

QUARANTINE_DIRECTORY = "rejected-publications"


def quarantine_recovery_publication(
    meetings_dir: Path,
    destination: Path,
    token: str,
) -> None:
    """Move only the exact token-bound directory out of the visible namespace."""

    canonical = meetings_dir.expanduser().resolve(strict=True)
    slug = validate_meeting_slug(destination.name)
    if destination.parent.resolve(strict=True) != canonical:
        raise ValueError("rejected recovery publication escaped MEETINGS_DIR")
    with _open_root(canonical) as root_fd:
        with _open_directory_at(root_fd, slug) as child_fd:
            child = os.fstat(child_fd)
            require_recovery_marker_directory(child_fd, token)
            visible = os.stat(slug, dir_fd=root_fd, follow_symlinks=False)
            expected = (child.st_dev, child.st_ino)
            if not stat.S_ISDIR(visible.st_mode) or expected != (
                visible.st_dev,
                visible.st_ino,
            ):
                raise ValueError("rejected recovery publication changed before quarantine")
            with _open_directory_at(root_fd, ".meeting-memory-staging") as staging_fd:
                with _open_private_quarantine(staging_fd) as quarantine_fd:
                    quarantine_name = f"{slug}.{uuid.uuid4().hex}"
                    os.rename(
                        slug,
                        quarantine_name,
                        src_dir_fd=root_fd,
                        dst_dir_fd=quarantine_fd,
                    )
                    with _open_directory_at(quarantine_fd, quarantine_name) as moved_fd:
                        moved = os.fstat(moved_fd)
                        if (moved.st_dev, moved.st_ino) != expected:
                            raise ValueError("wrong recovery publication was quarantined")
                    os.fsync(quarantine_fd)
                    os.fsync(root_fd)


@contextmanager
def _open_root(path: Path) -> Iterator[int]:
    descriptor = open_directory_tree(path)
    try:
        yield descriptor
    finally:
        os.close(descriptor)


@contextmanager
def _open_directory_at(parent_fd: int, name: str) -> Iterator[int]:
    descriptor = os.open(
        name,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
        dir_fd=parent_fd,
    )
    try:
        yield descriptor
    finally:
        os.close(descriptor)


@contextmanager
def _open_private_quarantine(staging_fd: int) -> Iterator[int]:
    try:
        os.mkdir(QUARANTINE_DIRECTORY, 0o700, dir_fd=staging_fd)
        os.fsync(staging_fd)
    except FileExistsError:
        # Another recovery may have created the shared private directory first.
        pass
    with _open_directory_at(staging_fd, QUARANTINE_DIRECTORY) as descriptor:
        if stat.S_IMODE(os.fstat(descriptor).st_mode) & 0o077:
            raise ValueError("recovery quarantine has unsafe permissions")
        yield descriptor

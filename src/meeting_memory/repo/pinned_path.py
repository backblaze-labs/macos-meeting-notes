"""Component-wise no-follow access to a local source's parent directory."""

from __future__ import annotations

import os
from pathlib import Path


def open_parent_directory(path: Path) -> int:
    """Pin every parent component without following directory symlinks."""

    absolute = path.expanduser()
    if not absolute.is_absolute():
        absolute = Path.cwd() / absolute
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in absolute.parent.parts[1:]:
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

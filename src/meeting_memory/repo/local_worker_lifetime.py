"""Parent-death containment for app-owned local workers and their private inputs."""

from __future__ import annotations

import contextlib
import fcntl
import os
import signal
import stat
import threading
import time
from collections.abc import Iterator
from pathlib import Path

PARENT_PID_ENV = "MEETING_MEMORY_LOCAL_PARENT_PID"
LOCK_FD_ENV = "MEETING_MEMORY_LOCAL_LOCK_FD"
TEMP_ROOT_ENV = "MEETING_MEMORY_LOCAL_TEMP_ROOT"
PARENT_CHECK_INTERVAL_SECONDS = 0.1
REQUEST_PREFIXES = ("meeting-memory-inference-", "meeting-memory-models-", "meeting-memory-probe-")


class PrivateWorkerDirectory:
    """Pin only a known private temp directory, never recursively delete content."""

    def __init__(self, path: Path, *, prefixes: tuple[str, ...], names: tuple[str, ...]) -> None:
        temp_root = Path(os.environ[TEMP_ROOT_ENV]).resolve(strict=True)
        if (
            path.parent.resolve(strict=True) != temp_root
            or not path.name.startswith(prefixes)
            or path.is_symlink()
        ):
            raise ValueError("worker cleanup directory is not app-owned")
        self.path = path
        self.names = names
        self.fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        info = os.fstat(self.fd)
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            os.close(self.fd)
            raise ValueError("worker cleanup directory must be private")
        self.identity = (info.st_dev, info.st_ino)

    def remove_owned_files(self) -> None:
        for name in self.names:
            try:
                os.unlink(name, dir_fd=self.fd)
            except OSError:
                pass
        try:
            current = self.path.lstat()
            if (current.st_dev, current.st_ino) == self.identity:
                self.path.rmdir()
        except OSError:
            pass

    def close(self) -> None:
        os.close(self.fd)


@contextlib.contextmanager
def worker_parent_lifetime(request: Path, row: dict) -> Iterator[None]:
    """Retain admission until death cleanup and process exit, including parent crashes."""

    expected_parent = int(os.environ[PARENT_PID_ENV])
    if expected_parent <= 1:
        raise ValueError("invalid worker parent")
    lock_fd = int(os.environ[LOCK_FD_ENV]) if LOCK_FD_ENV in os.environ else None
    if row["operation"] != "probe" and lock_fd is None:
        raise ValueError("a local operation requires the inherited admission lock")
    if lock_fd is not None:
        info = os.fstat(lock_fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError("invalid inherited admission descriptor")
        # flock follows the same inherited open-file description across exec.
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    directories = []
    try:
        directories.append(
            PrivateWorkerDirectory(
                request.parent, prefixes=REQUEST_PREFIXES, names=("request.json", "result.json")
            )
        )
        if row["operation"] == "infer":
            directories.append(
                PrivateWorkerDirectory(
                    Path(row["audio"]).parent,
                    prefixes=("meeting-memory-decoding-",),
                    names=("decoded.wav",),
                )
            )

        def terminate_owned_operation(*_args) -> None:
            for directory in directories:
                directory.remove_owned_files()
            # Keep admission open through cleanup and GPU/process teardown.
            os._exit(4)

        def watch_parent() -> None:
            while True:
                if os.getppid() != expected_parent:
                    terminate_owned_operation()
                time.sleep(PARENT_CHECK_INTERVAL_SECONDS)

        for signum in (signal.SIGTERM, signal.SIGINT):
            signal.signal(signum, terminate_owned_operation)
        watcher = threading.Thread(target=watch_parent, name="local-parent-watchdog", daemon=True)
        watcher.start()
        yield
    finally:
        if "watcher" not in locals():
            for directory in directories:
                directory.close()
        # One operation owns the entire child process. The watchdog, pinned directory
        # descriptors, signal handlers, and inherited admission fd deliberately remain
        # live until OS process exit, including Python/Metal teardown after this scope.

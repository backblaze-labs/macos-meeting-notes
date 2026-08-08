"""Per-meeting in-process and cross-process advisory locks."""

from __future__ import annotations

import fcntl
import hashlib
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_registry_guard = threading.Lock()
_thread_locks: dict[str, threading.RLock] = {}


@contextmanager
def meeting_lock(meetings_dir: Path, meeting_key: str) -> Iterator[None]:
    """Serialize updates to one meeting while allowing unrelated work."""

    resolved = str(meetings_dir.resolve())
    registry_key = f"{resolved}\0{meeting_key}"
    with _registry_guard:
        thread_lock = _thread_locks.setdefault(registry_key, threading.RLock())

    with thread_lock:
        lock_dir = meetings_dir / ".meeting-memory-locks"
        lock_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(meeting_key.encode("utf-8")).hexdigest()
        lock_path = lock_dir / f"{digest}.lock"
        with lock_path.open("a+b") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

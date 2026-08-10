"""Explicit runtime orchestration for once-only legacy temp recovery."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path

from meeting_memory.service.legacy_recovery_index import (
    discover_legacy_once,
    load_legacy_discovery_state,
    persist_legacy_discovery_complete,
)
from meeting_memory.service.local_commit import LocalRecordingCommitter
from meeting_memory.types.events import NotifyEvent
from meeting_memory.types.recovery import RecoveryIndexEntry, RecoveryOrigin

LOGGER = logging.getLogger(__name__)
EventSink = Callable[[object], None]
ThreadFactory = Callable[..., threading.Thread]


class LegacyRecoveryRuntime:
    """Scan only on request and retain discoveries until explicit commits finish."""

    def __init__(
        self,
        legacy_root: Path,
        marker_path: Path,
        committer: LocalRecordingCommitter,
        event_sink: EventSink,
        *,
        thread_factory: ThreadFactory = threading.Thread,
    ) -> None:
        self._legacy_root = legacy_root
        self._marker_path = marker_path
        self._committer = committer
        self._event_sink = event_sink
        self._thread_factory = thread_factory
        self._lock = threading.Lock()
        self._scan_started = False
        self._entries: dict[tuple[int, int], RecoveryIndexEntry] = {}
        self._active: set[tuple[int, int]] = set()

    @property
    def entries(self) -> tuple[RecoveryIndexEntry, ...]:
        with self._lock:
            return tuple(self._entries.values())

    def start_scan(self) -> None:
        with self._lock:
            if self._scan_started:
                return
            self._scan_started = True
        self._start(self._scan)

    def start_commit(self, entry: RecoveryIndexEntry) -> None:
        if entry.origin is not RecoveryOrigin.LEGACY_TEMP:
            raise ValueError("legacy runtime accepts only legacy recovery entries")
        key = _entry_key(entry)
        with self._lock:
            if self._entries.get(key) != entry or key in self._active:
                return
            self._active.add(key)
        self._start(self._commit, entry)

    def _scan(self) -> None:
        try:
            state = load_legacy_discovery_state(self._marker_path)
            result = discover_legacy_once(self._legacy_root, state)
            if not result.entries and not state.completed:
                persist_legacy_discovery_complete(self._marker_path)
            with self._lock:
                self._entries = {_entry_key(entry): entry for entry in result.entries}
        except Exception:
            with self._lock:
                self._scan_started = False
            LOGGER.warning("Legacy recovery scan failed")
            self._event_sink(
                NotifyEvent(
                    "Legacy recovery scan failed",
                    "No recordings were changed. Try again later.",
                    rebuild_menu=True,
                )
            )
            return
        count = len(result.entries)
        body = "No legacy recordings found." if count == 0 else f"{count} recording(s) found."
        self._event_sink(
            NotifyEvent("Legacy recovery scan complete", body, rebuild_menu=True)
        )

    def _commit(self, entry: RecoveryIndexEntry) -> None:
        key = _entry_key(entry)
        try:
            if self._committer.commit(entry, entry.meta) is None:
                return
            with self._lock:
                remaining = [
                    item for item_key, item in self._entries.items() if item_key != key
                ]
            if not remaining:
                try:
                    persist_legacy_discovery_complete(self._marker_path)
                except Exception:
                    LOGGER.warning("Legacy recovery completion marker could not be saved")
                    with self._lock:
                        self._scan_started = False
                    self._event_sink(
                        NotifyEvent(
                            "Legacy recovery state not saved",
                            "The recording was saved locally; retry the scan later.",
                            rebuild_menu=True,
                        )
                    )
            with self._lock:
                self._entries.pop(key, None)
        except Exception:
            LOGGER.warning("Legacy recording commit failed")
            self._event_sink(
                NotifyEvent(
                    "Recovered recording failed",
                    "The original recording remains available.",
                    rebuild_menu=True,
                )
            )
        finally:
            with self._lock:
                self._active.discard(key)

    def _start(self, callback: Callable[..., None], *args: object) -> None:
        try:
            self._thread_factory(target=callback, args=args, daemon=True).start()
        except Exception:
            if callback == self._scan:
                with self._lock:
                    self._scan_started = False
            elif args and isinstance(args[0], RecoveryIndexEntry):
                with self._lock:
                    self._active.discard(_entry_key(args[0]))
            LOGGER.warning("Legacy recovery worker could not start")
            self._event_sink(
                NotifyEvent(
                    "Legacy recovery could not start",
                    "No recordings were changed. Try again later.",
                    rebuild_menu=True,
                )
            )


def _entry_key(entry: RecoveryIndexEntry) -> tuple[int, int]:
    if entry.source_device is None or entry.source_inode is None:
        raise ValueError("legacy recovery entry must have a pinned source identity")
    return entry.source_device, entry.source_inode

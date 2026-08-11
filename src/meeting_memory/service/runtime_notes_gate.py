"""Monotonic current-session gate for explicit Notes generation."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path

from meeting_memory.types.egress import EgressPaused
from meeting_memory.types.events import NotifyEvent

LOGGER = logging.getLogger(__name__)


class RuntimeNotesGate:
    def __init__(
        self,
        generator: Callable[[Path], Path] | None,
        event_sink: Callable[[object], None],
        thread_factory: Callable[..., threading.Thread],
        allowed: Callable[[], bool],
    ) -> None:
        self._generator = generator
        self._event_sink = event_sink
        self._thread_factory = thread_factory
        self._allowed = allowed
        self._enabled = generator is not None
        self._lock = threading.Lock()

    def start(self, path: Path) -> None:
        self._thread_factory(target=self._run, args=(path,), daemon=True).start()

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._enabled = enabled and self._generator is not None

    def _run(self, path: Path) -> None:
        allowed = self._allowed()
        with self._lock:
            generator = self._generator if self._enabled and allowed else None
        if generator is None:
            body = (
                "Notes is disabled for this session."
                if not allowed
                else "Summarizer not configured"
            )
            self._event_sink(NotifyEvent("Notes generation failed", body))
            return
        try:
            notes_path = generator(path)
        except EgressPaused:
            self._event_sink(
                NotifyEvent("Notes generation stopped", "Notes is disabled for this session.")
            )
            return
        except Exception:
            LOGGER.warning("Notes generation failed")
            self._event_sink(
                NotifyEvent("Notes generation failed", "Transcript remains saved locally")
            )
            return
        self._event_sink(
            NotifyEvent(
                title="Notes generated",
                body=f"{notes_path.parent.name} · notes.md ready",
                action_label="Open",
                meeting_directory=notes_path.parent,
            )
        )

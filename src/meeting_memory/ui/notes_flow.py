"""Post-transcription Notes flow owned by the tray controller.

Wraps the session Notes gate with the two ways Notes can start: an explicit
action after manual speaker review, and the automatic path that keeps the
diarized labels and lets Calendar attendees guide the summarizer. Keeping it
out of ``controller.py`` keeps that module under the size limit.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path

from meeting_memory.service.runtime_notes_gate import RuntimeNotesGate
from meeting_memory.types.events import NotifyEvent

LOGGER = logging.getLogger(__name__)
ThreadFactory = Callable[..., threading.Thread]


class NotesFlow:
    """Start Notes only when the capability can run; never lock a transcript for nothing."""

    def __init__(
        self,
        generator: Callable[[Path], Path] | None,
        event_sink: Callable[[object], None],
        thread_factory: ThreadFactory,
        allowed: Callable[[], bool],
        confirm_kept_labels: Callable[[Path], Path],
    ) -> None:
        self._gate = RuntimeNotesGate(generator, event_sink, thread_factory, allowed)
        self._event_sink = event_sink
        self._thread_factory = thread_factory
        self._confirm_kept_labels = confirm_kept_labels

    @property
    def available(self) -> bool:
        """Return whether Notes is configured and not paused for this session."""

        return self._gate.available

    def generate(self, path: Path) -> None:
        """Start Notes for a transcript the user already reviewed."""

        self._gate.start(path)

    def set_enabled(self, enabled: bool) -> None:
        """Stop new generations; one already in flight finishes."""

        self._gate.set_enabled(enabled)

    def auto_generate(self, path: Path) -> None:
        """Keep the diarized labels off the UI thread, then start Notes.

        Notes is optional. When it is unconfigured or paused nothing happens:
        the transcript is not confirmed and no failure is reported, so the
        meeting stays open for manual review.
        """

        if not self.available:
            LOGGER.info("Automatic Notes skipped; Notes is unavailable for %s", path.name)
            return
        self._thread_factory(target=self._confirm_then_summarize, args=(path,), daemon=True).start()

    def _confirm_then_summarize(self, path: Path) -> None:
        try:
            self._confirm_kept_labels(path)
        except Exception:
            LOGGER.warning("Transcript could not be confirmed for Notes", exc_info=True)
            self._event_sink(NotifyEvent("Notes skipped", "No speaker labels in transcript."))
            return
        self._gate.start(path)

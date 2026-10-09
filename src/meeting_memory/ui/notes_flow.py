"""Start Notes from the single user-confirmed speaker review flow."""

import threading
from collections.abc import Callable
from pathlib import Path

from meeting_memory.service.runtime_notes_gate import RuntimeNotesGate


class NotesFlow:
    def __init__(
        self,
        generator: Callable[[Path], Path] | None,
        event_sink: Callable[[object], None],
        thread_factory: Callable[..., threading.Thread],
        allowed: Callable[[], bool],
    ) -> None:
        self._gate = RuntimeNotesGate(generator, event_sink, thread_factory, allowed)

    @property
    def available(self) -> bool:
        return self._gate.available

    def generate(self, path: Path) -> None:
        self._gate.start(path)

    def set_enabled(self, enabled: bool) -> None:
        self._gate.set_enabled(enabled)

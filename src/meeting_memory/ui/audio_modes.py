"""Switching the recording audio mode from the sidebar."""

from __future__ import annotations

from collections.abc import Callable

from meeting_memory.service.audio_modes import (
    AUDIO_MODES,
    AudioMode,
    apply_audio_mode,
)
from meeting_memory.types.events import NotifyEvent
from meeting_memory.ui.controller import TrayController

AudioModeApplier = Callable[[AudioMode, object], None]


class AudioModeMenu:
    """Tracks the selected mode and applies a change; `sidebar_view_model.py`
    turns it into rows and `on_change` refreshes the panel afterwards."""

    def __init__(
        self,
        rumps_module,
        controller: TrayController,
        *,
        on_change: Callable[[], None],
        applier: AudioModeApplier = apply_audio_mode,
    ) -> None:
        self.rumps = rumps_module
        self.controller = controller
        self.on_change = on_change
        self.applier = applier
        self.current_mode_key = getattr(controller.recorder, "capture_mode", AUDIO_MODES[0].key)

    def select_mode(self, mode: AudioMode) -> None:
        try:
            self.applier(mode, self.controller.recorder)
        except Exception as exc:
            self.controller.event_queue.put(
                NotifyEvent("Audio mode could not change", _format_exception(exc))
            )
            return

        self.current_mode_key = mode.key
        self.controller.event_queue.put(
            NotifyEvent(
                "Audio mode changed",
                f"{mode.label}: {mode.description}.",
            )
        )
        self.on_change()

    def _mode_label(self, mode: AudioMode) -> str:
        prefix = "✓ " if mode.key == self.current_mode_key else ""
        return f"{prefix}{mode.label}"


def _format_exception(exc: Exception) -> str:
    return str(exc).strip() or exc.__class__.__name__

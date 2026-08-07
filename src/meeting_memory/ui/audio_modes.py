"""Tray menu actions for switching recording audio modes."""

from __future__ import annotations

from collections.abc import Callable

from meeting_memory.service.audio_modes import (
    AUDIO_MODES,
    AudioMode,
    apply_audio_mode,
)
from meeting_memory.types.events import NotifyEvent
from meeting_memory.ui import menu
from meeting_memory.ui.controller import TrayController

AudioModeApplier = Callable[[AudioMode, object], None]


class AudioModeMenu:
    def __init__(
        self,
        rumps_module,
        controller: TrayController,
        *,
        rebuild_menu: Callable[[], None],
        applier: AudioModeApplier = apply_audio_mode,
    ) -> None:
        self.rumps = rumps_module
        self.controller = controller
        self.rebuild_menu = rebuild_menu
        self.applier = applier
        self.current_mode_key = getattr(controller.recorder, "capture_mode", AUDIO_MODES[0].key)

    def add_items(self, app_menu) -> None:
        app_menu.add(self.rumps.MenuItem(menu.AUDIO_MODE_HEADER, callback=None))
        for mode in AUDIO_MODES:
            app_menu.add(
                self.rumps.MenuItem(
                    self._mode_label(mode),
                    callback=lambda _sender, item=mode: self.select_mode(item),
                )
            )
        app_menu.add(None)

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
        self.rebuild_menu()

    def _mode_label(self, mode: AudioMode) -> str:
        prefix = "✓ " if mode.key == self.current_mode_key else ""
        return f"{prefix}{mode.label}"

def _format_exception(exc: Exception) -> str:
    return str(exc).strip() or exc.__class__.__name__

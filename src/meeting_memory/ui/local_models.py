"""Main-thread model controls; all readiness and preparation run on workers."""

from __future__ import annotations

from meeting_memory.service.local_model_preparation import LocalModelPreparationCoordinator
from meeting_memory.types.events import TranscriptionFailed, TranscriptionProgress, TranscriptReady
from meeting_memory.types.local_model_preparation import LocalModelState, LocalModelsUpdated
from meeting_memory.ui.local_model_panel import create_model_panel


class LocalModelsUI:
    def __init__(
        self,
        event_sink,
        rumps_module,
        *,
        coordinator=None,
        panel_factory=None,
        on_change=lambda: None,
        provider=None,
    ):
        self.coordinator = coordinator or LocalModelPreparationCoordinator(event_sink)
        self._rumps = rumps_module
        self._panel_factory = panel_factory or create_model_panel
        self._panel = None
        self._on_change = on_change
        self._event = None
        self._inference = None
        self._provider = provider

    @property
    def progress_label(self):
        if self._inference or self._provider is None:
            return self._inference
        name = (
            "AssemblyAI (external)" if self._provider == "assemblyai" else "Local (Apple Silicon)"
        )
        return f"Transcription provider: {name}"

    def open(self):
        try:
            if self._panel is None:
                self._panel = self._panel_factory(self.prepare, self.cancel)
                self._render()
            self._panel.show()
            if not self.coordinator.busy:
                self.coordinator.check()
        except Exception:
            self._rumps.alert(
                title="Local model controls could not open.",
                message="Close other dialogs and try Prepare Local Models again.",
            )

    def prepare(self):
        if self.coordinator.prepare() is not None:
            self._render(busy=True)

    def cancel(self):
        if self.coordinator.cancel() and self._panel is not None:
            self._panel.update(
                summary="Cancelling local preparation.",
                details="Waiting for the model worker to stop. Shared files are preserved.",
                busy=True,
                prepare_enabled=False,
                retry=False,
                fraction=None,
            )

    def handle_event(self, event):
        if not isinstance(event, LocalModelsUpdated):
            return False
        if self.coordinator.is_current(event.operation_id):
            self._event = event
            self._render()
            self._on_change()
        return True

    def handle_runtime_event(self, event):
        if isinstance(event, TranscriptionProgress):
            self.transcription_progress(event)
            return True
        if isinstance(event, (TranscriptReady, TranscriptionFailed)):
            self.transcription_finished()
        return False

    def transcription_progress(self, event):
        self._inference = f"Local transcription: {event.progress.message}"
        self._on_change()

    def transcription_finished(self):
        if self._inference is not None:
            self._inference = None
            self._on_change()

    def _render(self, *, busy=None):
        if self._panel is None:
            return
        event = self._event
        busy = self.coordinator.busy if busy is None else busy
        status = event.status if event else None
        allowed = status is None or (status.supported and status.runtime_available)
        details = event.action if event else "Checking this Mac and the local model cache."
        fraction = progress_fraction(event.progress) if event else None
        if fraction is not None:
            progress = event.progress
            details = f"Downloaded {progress.completed_bytes:,} of {progress.total_bytes:,} bytes."
        self._panel.update(
            summary=event.summary if event else "Checking local models.",
            details=details,
            busy=busy,
            prepare_enabled=allowed,
            retry=event is not None
            and event.state in {LocalModelState.FAILED, LocalModelState.CANCELLED},
            fraction=fraction,
        )


def progress_fraction(progress):
    if progress is None:
        return None
    completed, total = progress.completed_bytes, progress.total_bytes
    if (
        type(completed) is not int
        or type(total) is not int
        or total <= 0
        or completed < 0
        or completed > total
    ):
        return None
    return completed / total

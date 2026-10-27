"""Explicit history retry confirmation using the captured effective provider."""

from meeting_memory.types.transcription import TranscriptionProvider
from meeting_memory.ui.modal_focus import run_modal


def confirm_transcription_retry(settings) -> bool:
    from AppKit import NSAlert

    provider = getattr(settings, "transcription_provider", TranscriptionProvider.LOCAL)
    external = provider == TranscriptionProvider.ASSEMBLYAI
    name = "AssemblyAI (external)" if external else "Local (Apple Silicon)"
    alert = NSAlert.alloc().init()
    alert.setMessageText_("Retry pending or failed transcriptions?")
    message = f"Use the current-session provider: {name}. Successful transcripts are unchanged. "
    message += (
        "Audio will leave this Mac and be sent to AssemblyAI under your accepted controls."
        if external
        else "Speech recognition and diarization run on this Mac. Prepare local models first."
    )
    alert.setInformativeText_(message)
    alert.addButtonWithTitle_("Retry Transcriptions")
    alert.addButtonWithTitle_("Cancel")
    return run_modal(alert) in {1, 1000}

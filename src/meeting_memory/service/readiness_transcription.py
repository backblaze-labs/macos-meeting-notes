"""Provider-specific local-only Transcription readiness without loading model weights."""

from meeting_memory.config.runtime import RuntimeSettings
from meeting_memory.repo.local_models import inspect_local_backend
from meeting_memory.types.capabilities import Capability, CapabilityState, CapabilityStatus
from meeting_memory.types.transcription import TranscriptionProvider


def transcription_status(settings: RuntimeSettings) -> CapabilityStatus:
    config = settings.transcription
    if config is None:
        return CapabilityStatus(
            Capability.TRANSCRIPTION,
            CapabilityState.UNCONFIGURED,
            "Transcription is not enabled; committed recordings remain available.",
            "Open Configuration > Transcription to choose Local, or explicitly accept AssemblyAI.",
        )
    if config.provider is TranscriptionProvider.ASSEMBLYAI:
        return CapabilityStatus(
            Capability.TRANSCRIPTION,
            CapabilityState.READY,
            "AssemblyAI external transcription is explicitly enabled for new recordings.",
        )
    status = inspect_local_backend(probe_metal=True)
    state = CapabilityState.READY
    if not status.supported or not status.runtime_available:
        state = CapabilityState.FAILED
    elif not status.models_ready:
        state = CapabilityState.UNCONFIGURED
    return CapabilityStatus(
        Capability.TRANSCRIPTION,
        state,
        status.summary,
        None if state is CapabilityState.READY else status.action,
    )

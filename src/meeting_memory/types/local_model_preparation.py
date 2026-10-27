"""Worker-to-main-thread events for explicit local model preparation."""

from dataclasses import dataclass
from enum import StrEnum

from meeting_memory.types.local_transcription import LocalBackendStatus, LocalModelProgress


class LocalModelState(StrEnum):
    CHECKING = "checking"
    AVAILABLE = "available"
    PREPARING = "preparing"
    READY = "ready"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class LocalModelsUpdated:
    operation_id: str
    state: LocalModelState
    summary: str
    action: str = ""
    status: LocalBackendStatus | None = None
    progress: LocalModelProgress | None = None

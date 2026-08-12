"""Pure capability and readiness boundary data."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Capability(StrEnum):
    """Stable product capability identifiers."""

    RECORDING_CORE = "recording_core"
    TRANSCRIPTION = "transcription"
    BACKUP = "backup"
    CALENDAR = "calendar"
    NOTES = "notes"

    @property
    def label(self) -> str:
        """Stable human-facing capability name."""

        return {
            Capability.RECORDING_CORE: "Recording Core",
            Capability.TRANSCRIPTION: "Transcription",
            Capability.BACKUP: "Backup",
            Capability.CALENDAR: "Calendar",
            Capability.NOTES: "Notes",
        }[self]


class CapabilityState(StrEnum):
    """Shared lifecycle states for every capability."""

    UNCONFIGURED = "unconfigured"
    CHECKING = "checking"
    READY = "ready"
    DEGRADED = "degraded"
    FAILED = "failed"


class MeetingJobState(StrEnum):
    """Durable state for optional work attached to one meeting."""

    NOT_REQUESTED = "not_requested"
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class CapabilityStatus:
    """One capability's current state and user-facing recovery context."""

    capability: Capability
    state: CapabilityState
    summary: str
    action: str | None = None

    def __post_init__(self) -> None:
        if not self.summary.strip():
            raise ValueError("capability status summary must not be blank")
        if self.action is not None and not self.action.strip():
            raise ValueError("capability status action must not be blank")
        actionable_states = {
            CapabilityState.UNCONFIGURED,
            CapabilityState.DEGRADED,
            CapabilityState.FAILED,
        }
        if self.state in actionable_states and self.action is None:
            raise ValueError(f"{self.state.value} capability status requires an action")

    @property
    def usable(self) -> bool:
        """Return whether safe capability actions may remain enabled."""

        return self.state in {CapabilityState.READY, CapabilityState.DEGRADED}


@dataclass(frozen=True)
class ReadinessReport:
    """Capability-indexed readiness for local capture and required B2 backup."""

    statuses: tuple[CapabilityStatus, ...]

    def __post_init__(self) -> None:
        capabilities = [status.capability for status in self.statuses]
        if len(capabilities) != len(set(capabilities)):
            raise ValueError("readiness report contains duplicate capabilities")
        missing = set(Capability) - set(capabilities)
        if missing:
            labels = ", ".join(sorted(capability.value for capability in missing))
            raise ValueError(f"readiness report is missing capabilities: {labels}")
        by_capability = {status.capability: status for status in self.statuses}
        object.__setattr__(
            self,
            "statuses",
            tuple(by_capability[capability] for capability in Capability),
        )

    def status_for(self, capability: Capability) -> CapabilityStatus:
        """Return the status for a capability in the complete report."""

        return next(status for status in self.statuses if status.capability is capability)

    @property
    def recording_ready(self) -> bool:
        """Return whether the local first-value recording path is usable."""

        return self.status_for(Capability.RECORDING_CORE).usable

    @property
    def setup_ready(self) -> bool:
        """Return whether required Recording Core and B2 setup are usable."""

        return self.recording_ready and self.status_for(Capability.BACKUP).usable

    @property
    def optional_attention(self) -> tuple[CapabilityStatus, ...]:
        """Return provider capabilities that need attention."""

        return tuple(
            status
            for status in self.statuses
            if status.capability is not Capability.RECORDING_CORE
            and status.state in {CapabilityState.DEGRADED, CapabilityState.FAILED}
        )

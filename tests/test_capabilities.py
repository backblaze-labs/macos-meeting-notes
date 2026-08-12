"""Tests for the pure local-first capability contract types."""

from __future__ import annotations

import pytest

from meeting_memory.types.capabilities import (
    Capability,
    CapabilityState,
    CapabilityStatus,
    MeetingJobState,
    ReadinessReport,
)


def test_setup_requires_recording_core_and_backup() -> None:
    report = _report(
        CapabilityStatus(
            Capability.RECORDING_CORE,
            CapabilityState.READY,
            "Local recording is ready.",
        ),
        transcription=CapabilityState.UNCONFIGURED,
        backup=CapabilityState.FAILED,
        calendar=CapabilityState.CHECKING,
        notes=CapabilityState.DEGRADED,
    )

    assert report.recording_ready is True
    assert report.setup_ready is False
    assert [status.capability for status in report.optional_attention] == [
        Capability.BACKUP,
        Capability.NOTES,
    ]

    ready = _report(
        CapabilityStatus(
            Capability.RECORDING_CORE,
            CapabilityState.READY,
            "Local recording is ready.",
        ),
        backup=CapabilityState.READY,
    )
    assert ready.setup_ready is True


@pytest.mark.parametrize(
    ("state", "usable"),
    [
        (CapabilityState.UNCONFIGURED, False),
        (CapabilityState.CHECKING, False),
        (CapabilityState.READY, True),
        (CapabilityState.DEGRADED, True),
        (CapabilityState.FAILED, False),
    ],
)
def test_capability_state_usable_semantics(state: CapabilityState, usable: bool) -> None:
    action = (
        "Take the recommended action."
        if state
        in {
            CapabilityState.UNCONFIGURED,
            CapabilityState.DEGRADED,
            CapabilityState.FAILED,
        }
        else None
    )
    status = CapabilityStatus(Capability.RECORDING_CORE, state, "Status summary.", action)

    assert status.usable is usable


def test_readiness_report_requires_each_capability_once() -> None:
    statuses = tuple(
        CapabilityStatus(
            capability,
            CapabilityState.UNCONFIGURED,
            "Not configured.",
            "Configure this capability.",
        )
        for capability in Capability
        if capability is not Capability.NOTES
    )

    with pytest.raises(ValueError, match="missing capabilities: notes"):
        ReadinessReport(statuses)

    complete = _report(
        CapabilityStatus(
            Capability.RECORDING_CORE,
            CapabilityState.DEGRADED,
            "System-only recording is available.",
            "Select a microphone for Full Meeting.",
        )
    )
    with pytest.raises(ValueError, match="duplicate capabilities"):
        ReadinessReport((*complete.statuses, complete.statuses[0]))


def test_readiness_report_canonicalizes_capability_order() -> None:
    report = _report(
        CapabilityStatus(
            Capability.RECORDING_CORE,
            CapabilityState.READY,
            "Local recording is ready.",
        )
    )

    shuffled = ReadinessReport(tuple(reversed(report.statuses)))

    assert [status.capability for status in shuffled.statuses] == list(Capability)


def test_capability_status_rejects_blank_user_facing_text() -> None:
    with pytest.raises(ValueError, match="summary"):
        CapabilityStatus(Capability.BACKUP, CapabilityState.FAILED, " ")
    with pytest.raises(ValueError, match="action"):
        CapabilityStatus(Capability.BACKUP, CapabilityState.FAILED, "Unavailable.", "")


@pytest.mark.parametrize(
    "state",
    [
        CapabilityState.UNCONFIGURED,
        CapabilityState.DEGRADED,
        CapabilityState.FAILED,
    ],
)
def test_actionable_capability_states_require_recovery_action(
    state: CapabilityState,
) -> None:
    with pytest.raises(ValueError, match="requires an action"):
        CapabilityStatus(Capability.BACKUP, state, "Needs attention.")


def test_meeting_job_states_are_distinct_from_capability_readiness() -> None:
    assert [state.value for state in MeetingJobState] == [
        "not_requested",
        "pending",
        "running",
        "succeeded",
        "failed",
    ]
    assert MeetingJobState is not CapabilityState
    assert type(MeetingJobState.FAILED) is MeetingJobState
    assert type(CapabilityState.FAILED) is CapabilityState


def _report(
    recording: CapabilityStatus,
    *,
    transcription: CapabilityState = CapabilityState.UNCONFIGURED,
    backup: CapabilityState = CapabilityState.UNCONFIGURED,
    calendar: CapabilityState = CapabilityState.UNCONFIGURED,
    notes: CapabilityState = CapabilityState.UNCONFIGURED,
) -> ReadinessReport:
    def optional_status(
        capability: Capability,
        state: CapabilityState,
    ) -> CapabilityStatus:
        action = (
            "Configure or repair this capability."
            if state
            in {
                CapabilityState.UNCONFIGURED,
                CapabilityState.DEGRADED,
                CapabilityState.FAILED,
            }
            else None
        )
        return CapabilityStatus(capability, state, f"{capability.value} status.", action)

    return ReadinessReport(
        (
            recording,
            optional_status(Capability.TRANSCRIPTION, transcription),
            optional_status(Capability.BACKUP, backup),
            optional_status(Capability.CALENDAR, calendar),
            optional_status(Capability.NOTES, notes),
        )
    )

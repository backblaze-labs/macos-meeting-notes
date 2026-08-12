"""Tests for capability-aware doctor output and exit semantics."""

from __future__ import annotations

import pytest

from meeting_memory import doctor
from meeting_memory.types.capabilities import (
    Capability,
    CapabilityState,
    CapabilityStatus,
    ReadinessReport,
)


def test_doctor_renders_all_capabilities_and_actions() -> None:
    report = _report(CapabilityState.READY)

    rendered = doctor.render_results(report)

    assert [line for line in rendered.splitlines() if line.startswith("[")] == [
        "[READY] Recording Core: Recording Core summary.",
        "[UNCONFIGURED] Transcription: Transcription summary.",
        "[UNCONFIGURED] Backup: Backup summary.",
        "[UNCONFIGURED] Calendar: Calendar summary.",
        "[UNCONFIGURED] Notes: Notes summary.",
    ]
    assert rendered.count("action:") == 4


@pytest.mark.parametrize(
    ("core_state", "backup_state", "expected"),
    [
        (CapabilityState.READY, CapabilityState.READY, 0),
        (CapabilityState.DEGRADED, CapabilityState.READY, 0),
        (CapabilityState.READY, CapabilityState.DEGRADED, 0),
        (CapabilityState.READY, CapabilityState.UNCONFIGURED, 1),
        (CapabilityState.READY, CapabilityState.FAILED, 1),
        (CapabilityState.FAILED, CapabilityState.READY, 1),
        (CapabilityState.CHECKING, CapabilityState.READY, 1),
    ],
)
def test_default_doctor_exit_requires_recording_core_and_backup(
    core_state: CapabilityState,
    backup_state: CapabilityState,
    expected: int,
    monkeypatch,
) -> None:
    report = _report(
        core_state,
        optional_state=CapabilityState.FAILED,
        backup_state=backup_state,
    )
    monkeypatch.setattr(doctor, "run_checks", lambda: report)

    assert doctor.main(()) == expected


def _report(
    core_state: CapabilityState,
    *,
    optional_state: CapabilityState = CapabilityState.UNCONFIGURED,
    backup_state: CapabilityState | None = None,
) -> ReadinessReport:
    def status(capability: Capability, state: CapabilityState) -> CapabilityStatus:
        action = None
        if state in {
            CapabilityState.UNCONFIGURED,
            CapabilityState.DEGRADED,
            CapabilityState.FAILED,
        }:
            action = f"Repair {capability.label}."
        return CapabilityStatus(capability, state, f"{capability.label} summary.", action)

    return ReadinessReport(
        tuple(
            status(
                capability,
                (
                    core_state
                    if capability is Capability.RECORDING_CORE
                    else backup_state
                    if capability is Capability.BACKUP and backup_state is not None
                    else optional_state
                ),
            )
            for capability in Capability
        )
    )

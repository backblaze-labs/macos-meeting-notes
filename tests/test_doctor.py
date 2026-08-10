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
    ("state", "expected"),
    [
        (CapabilityState.READY, 0),
        (CapabilityState.DEGRADED, 0),
        (CapabilityState.FAILED, 1),
        (CapabilityState.CHECKING, 1),
    ],
)
def test_default_doctor_exit_depends_only_on_recording_core(
    state: CapabilityState,
    expected: int,
    monkeypatch,
) -> None:
    report = _report(state, optional_state=CapabilityState.FAILED)
    monkeypatch.setattr(doctor, "run_checks", lambda: report)

    assert doctor.main(()) == expected


def _report(
    core_state: CapabilityState,
    *,
    optional_state: CapabilityState = CapabilityState.UNCONFIGURED,
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
                core_state if capability is Capability.RECORDING_CORE else optional_state,
            )
            for capability in Capability
        )
    )

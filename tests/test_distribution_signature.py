"""Developer ID verification covers every executable slice, not only the app."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts import verify_distribution as verifier


def _runner(team: str, *, forbidden_entitlement: bool = False):
    inspected: list[Path] = []

    def runner(command, **kwargs):
        del kwargs
        command = list(command)
        if command[:3] == ["/usr/bin/codesign", "-d", "--verbose=4"]:
            target = Path(command[-1])
            inspected.append(target)
            identifier = (
                "com.meeting-memory.app" if target.name == "Meeting Memory.app" else target.name
            )
            details = (
                f"Identifier={identifier}\n"
                "Authority=Developer ID Application: Owner (TEAM123)\n"
                f"TeamIdentifier={team}\n"
                "Timestamp=Aug 11, 2026\n"
                "flags=0x10000(runtime)\n"
            )
            return subprocess.CompletedProcess(command, 0, stdout="", stderr=details)
        if "--entitlements" in command:
            entitlement = "com.apple.security.get-task-allow" if forbidden_entitlement else ""
            return subprocess.CompletedProcess(command, 0, stdout=entitlement, stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    return runner, inspected


def test_developer_id_verification_inspects_app_and_every_macho(tmp_path: Path) -> None:
    app = tmp_path / "Meeting Memory.app"
    helper = app / "Contents/MacOS/MeetingMemoryCapture"
    extension = app / "Contents/Frameworks/module.so"
    runner, inspected = _runner("TEAM123")

    verifier._verify_signature(
        app,
        (helper, extension),
        "developer-id",
        "TEAM123",
        runner,
    )

    assert inspected == [app, helper, extension]


@pytest.mark.parametrize(
    ("signed_team", "expected_team"),
    [("OTHERTEAM", "TEAM123"), ("TEAM123", "")],
)
def test_developer_id_verification_rejects_wrong_or_missing_team(
    tmp_path: Path,
    signed_team: str,
    expected_team: str,
) -> None:
    app = tmp_path / "Meeting Memory.app"
    runner, _inspected = _runner(signed_team)

    with pytest.raises(RuntimeError, match="expected team|team identifier"):
        verifier._verify_signature(app, (), "developer-id", expected_team, runner)


def test_forbidden_entitlement_on_nested_code_is_rejected(tmp_path: Path) -> None:
    app = tmp_path / "Meeting Memory.app"
    helper = app / "Contents/MacOS/MeetingMemoryCapture"
    runner, _inspected = _runner("TEAM123", forbidden_entitlement=True)

    with pytest.raises(RuntimeError, match="forbidden hardened-runtime"):
        verifier._verify_signature(
            app,
            (helper,),
            "developer-id",
            "TEAM123",
            runner,
        )

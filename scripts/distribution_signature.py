"""Verify macOS distribution signatures without exposing command output."""

from __future__ import annotations

from pathlib import Path

FORBIDDEN_ENTITLEMENTS = {
    "com.apple.security.cs.allow-jit",
    "com.apple.security.cs.allow-unsigned-executable-memory",
    "com.apple.security.cs.disable-library-validation",
    "com.apple.security.get-task-allow",
}


def verify_signature(
    app: Path,
    macho_files: tuple[Path, ...],
    signature: str,
    team_id: str | None,
    runner,
) -> None:
    runner(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)], check=True)
    if signature == "developer-id" and (not team_id or "\x00" in team_id):
        raise RuntimeError("Developer ID verification requires the expected team")
    for target in (app, *macho_files):
        details = runner(
            ["/usr/bin/codesign", "-d", "--verbose=4", str(target)],
            check=True,
            capture_output=True,
            text=True,
        )
        output = details.stderr + details.stdout
        if signature == "adhoc" and "Signature=adhoc" not in output:
            raise RuntimeError("expected an ad-hoc signature")
        if signature == "developer-id":
            if "Authority=Developer ID Application:" not in output:
                raise RuntimeError("expected a Developer ID Application signature")
            if f"TeamIdentifier={team_id}" not in output:
                raise RuntimeError("signed code has an unexpected team identifier")
            if "(runtime)" not in output or "Timestamp=" not in output:
                raise RuntimeError("signed code is missing hardened runtime or secure timestamp")
            if target == app and "Identifier=com.meeting-memory.app" not in output:
                raise RuntimeError("application designated identifier changed")
        entitlements = runner(
            ["/usr/bin/codesign", "-d", "--entitlements", ":-", str(target)],
            check=False,
            capture_output=True,
            text=True,
        )
        if any(
            item in entitlements.stdout + entitlements.stderr for item in FORBIDDEN_ENTITLEMENTS
        ):
            raise RuntimeError("bundle contains a forbidden hardened-runtime exception")

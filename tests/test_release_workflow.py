"""The release workflow is explicit, protected, and credential-gated."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/release.yml"


def test_release_workflow_is_manual_protected_and_tag_bound() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in text
    assert "pull_request:" not in text
    assert "push:" not in text
    assert text.count("environment: release") == 2
    assert "validate_release_context.py" in text
    assert "ref: ${{ inputs.tag }}" in text
    assert "persist-credentials: false" in text
    assert "permissions:\n  contents: read" in text
    assert "contents: write" in text


def test_release_workflow_pins_actions_and_uses_thin_native_matrix() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    action_refs = re.findall(r"uses: [^@\s]+@([0-9a-f]{40})", text)

    assert len(action_refs) == 5
    assert text.count("# v7") == 4
    assert text.count("# v8") == 1
    assert "runner: macos-15\n            arch: arm64" in text
    assert "runner: macos-15-intel\n            arch: x86_64" in text
    assert "requirements-distribution.lock" in text


def test_release_workflow_uses_ephemeral_signing_and_notarization() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    for required in (
        "APPLE_DEVELOPER_ID_P12_BASE64",
        "APPLE_DEVELOPER_ID_P12_PASSWORD",
        "APPLE_NOTARY_KEY_P8_BASE64",
        "APPLE_NOTARY_KEY_ID",
        "APPLE_NOTARY_ISSUER_ID",
        "APPLE_SIGNING_IDENTITY",
        "APPLE_TEAM_ID",
        "security create-keychain",
        "security delete-keychain",
        "release_distribution.py",
        "gh release create",
    ):
        assert required in text
    for forbidden in (
        "--deep",
        "get-task-allow",
        "disable-library-validation",
        "allow-jit",
        "allow-unsigned-executable-memory",
    ):
        assert forbidden not in text

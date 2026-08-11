"""Distribution orchestration preserves architecture and signing order."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts import build_distribution as builder
from scripts import verify_distribution as verifier


def test_build_requires_matching_native_architecture(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(builder.platform, "machine", lambda: "arm64")

    with pytest.raises(ValueError, match="matching native"):
        builder.build_distribution("x86_64", "-", tmp_path)


def test_build_copies_helper_then_signs_helper_and_outer_app(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[tuple[list[str], dict]] = []
    monkeypatch.setattr(builder.platform, "machine", lambda: "arm64")

    def fake_helper(_root, output, *, runner):
        del runner
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"native")
        output.chmod(0o755)
        return output

    def runner(command, **kwargs):
        calls.append((list(command), kwargs))
        if command[:2] == ["/usr/bin/lipo", "-archs"]:
            return subprocess.CompletedProcess(command, 0, stdout="arm64\n")
        if "PyInstaller" in command:
            app = tmp_path / "arm64/Meeting Memory.app/Contents/MacOS"
            app.mkdir(parents=True)
            (app / "Meeting Memory").write_bytes(b"executable")
        return subprocess.CompletedProcess(command, 0, stdout="")

    monkeypatch.setattr(builder, "build_native_capture_helper", fake_helper)

    app = builder.build_distribution("arm64", "-", tmp_path, runner=runner)

    helper = app / "Contents/MacOS/MeetingMemoryCapture"
    signing = [
        command for command, _kwargs in calls if command[:2] == ["/usr/bin/codesign", "--force"]
    ]
    pyinstaller = next((command, kwargs) for command, kwargs in calls if "PyInstaller" in command)
    assert helper.read_bytes() == b"native"
    assert [Path(command[-1]) for command in signing] == [helper, app]
    assert all("--deep" not in command for command in signing)
    assert pyinstaller[1]["env"]["MEETING_MEMORY_TARGET_ARCH"] == "arm64"
    assert pyinstaller[1]["env"]["MEETING_MEMORY_CODESIGN_IDENTITY"] == ""
    assert pyinstaller[1]["env"]["PYINSTALLER_CONFIG_DIR"].endswith("pyinstaller-cache")


def test_verifier_reports_only_allowlisted_stage_on_failure(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    sentinel = "private-build-path-sentinel"

    def fail(*_args, **_kwargs):
        raise verifier.DistributionVerificationError("relocated-smoke") from RuntimeError(sentinel)

    monkeypatch.setattr(verifier, "verify_distribution", fail)
    result = verifier.main(
        [
            "--app",
            str(tmp_path / "Meeting Memory.app"),
            "--arch",
            "arm64",
            "--signature",
            "adhoc",
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert captured.err == "Distribution verification failed safely at relocated-smoke.\n"
    assert sentinel not in captured.err


def test_build_path_scan_ignores_global_python_prefix_but_keeps_virtualenv(
    tmp_path: Path,
    monkeypatch,
) -> None:
    global_prefix = tmp_path / "managed-python"
    monkeypatch.setattr(verifier, "ROOT", tmp_path / "checkout")
    monkeypatch.setattr(verifier.sys, "prefix", str(global_prefix))
    monkeypatch.setattr(verifier.sys, "base_prefix", str(global_prefix))

    assert verifier._build_path_sentinels() == (
        ("checkout-path", str(tmp_path / "checkout").encode()),
    )

    monkeypatch.setattr(verifier.sys, "prefix", str(tmp_path / ".venv"))
    assert verifier._build_path_sentinels() == (
        ("checkout-path", str(tmp_path / "checkout").encode()),
        ("python-prefix", str(tmp_path / ".venv").encode()),
    )


def test_relocated_smoke_reports_value_free_self_check_stage(tmp_path: Path) -> None:
    app = tmp_path / "Meeting Memory.app"
    executable = app / "Contents/MacOS/Meeting Memory"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"app")

    def runner(command, **kwargs):
        del kwargs
        output = (
            f"meeting-memory {verifier.APP_VERSION}\n" if "--version" in command else "not-json"
        )
        return subprocess.CompletedProcess(command, 0, stdout=output)

    with pytest.raises(verifier.DistributionVerificationError) as raised:
        verifier._verify_smoke(app, runner)

    assert raised.value.stage == "self-check-result"


def test_relocated_smoke_extracts_only_allowlisted_child_stage(tmp_path: Path) -> None:
    app = tmp_path / "Meeting Memory.app"
    executable = app / "Contents/MacOS/Meeting Memory"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"app")

    def runner(command, **kwargs):
        del kwargs
        if "--version" in command:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=f"meeting-memory {verifier.APP_VERSION}\n",
            )
        raise subprocess.CalledProcessError(
            verifier.BUNDLE_SELF_CHECK_EXIT_CODES["import-keyring-backends-macOS"],
            command,
            output=(
                "private-bootstrap-sentinel\n"
                "Bundle self-check failed safely at import-keyring-backends-macOS. "
                "Reinstall the app.\nprivate-trailing-sentinel\n"
            ),
        )

    with pytest.raises(verifier.DistributionVerificationError) as raised:
        verifier._verify_smoke(app, runner)

    assert raised.value.stage == "self-check-import-keyring-backends-macOS"

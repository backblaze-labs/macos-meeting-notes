"""Distribution orchestration preserves architecture and signing order."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts import build_distribution as builder


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

"""Tests for clickable macOS app bundle installation."""

from __future__ import annotations

import plistlib
import subprocess
from pathlib import Path

from meeting_memory.repo.native_audio_build import ENCODER_NAME
from meeting_memory.service.macos_app import (
    APP_ICON_FILE,
    APP_NAME,
    BUNDLE_IDENTIFIER,
    install_macos_app,
    macos_app_executable,
    reload_macos_app,
)


def _fake_helper_builder(project_dir, output_path, *, runner):
    del project_dir, runner
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(b"native-helper")
    output_path.chmod(0o755)
    encoder = output_path.with_name(ENCODER_NAME)
    encoder.write_bytes(b"native-encoder")
    encoder.chmod(0o755)
    return output_path


def test_install_macos_app_writes_bundle(tmp_path: Path) -> None:
    calls = []
    project_dir = tmp_path / "project"
    app_path = tmp_path / "Applications" / "Meeting Memory.app"
    project_dir.mkdir()
    (project_dir / "src").mkdir()
    stale_encoder = app_path / "Contents/MacOS/MeetingMemoryAudioEncoder"
    stale_encoder.parent.mkdir(parents=True)
    stale_encoder.write_bytes(b"stale")

    def runner(args, check, **kwargs):
        calls.append((args, check))
        return subprocess.CompletedProcess(args, 0, stdout="")

    result = install_macos_app(
        project_dir=project_dir,
        app_path=app_path,
        python_executable="/venv/bin/python",
        runner=runner,
        helper_builder=_fake_helper_builder,
    )

    plist = plistlib.loads((app_path / "Contents" / "Info.plist").read_bytes())
    executable = app_path / "Contents" / "MacOS" / APP_NAME
    icon = app_path / "Contents" / "Resources" / APP_ICON_FILE
    helper = app_path / "Contents" / "MacOS" / "MeetingMemoryCapture"
    encoder = app_path / "Contents" / "MacOS" / ENCODER_NAME

    assert result == app_path
    assert plist["CFBundleName"] == APP_NAME
    assert plist["CFBundleIconFile"] == APP_ICON_FILE
    assert plist["CFBundleIdentifier"] == BUNDLE_IDENTIFIER
    assert plist["LSUIElement"] is True
    assert plist["NSPrincipalClass"] == "NSApplication"
    assert plist["LSMinimumSystemVersion"] == "15.0"
    assert "system audio" in plist["NSScreenCaptureUsageDescription"]
    assert executable.exists()
    assert icon.exists()
    assert icon.read_bytes()[:4] == b"icns"
    assert helper.read_bytes() == b"native-helper"
    assert helper.stat().st_mode & 0o111
    assert encoder.read_bytes() == b"native-encoder"
    assert encoder.stat().st_mode & 0o111
    assert not stale_encoder.exists()
    assert executable.stat().st_mode & 0o111
    assert f"cd {project_dir}" in executable.read_text(encoding="utf-8")
    if calls:
        assert calls[0][0][-2:] == ["-f", str(app_path)]


def test_reload_macos_app_installs_quits_and_opens(tmp_path: Path) -> None:
    calls = []
    project_dir = tmp_path / "project"
    app_path = tmp_path / "Applications" / "Meeting Memory.app"
    project_dir.mkdir()

    def runner(args, check, **kwargs):
        calls.append((args, check))
        return subprocess.CompletedProcess(args, 0, stdout="")

    result = reload_macos_app(
        project_dir=project_dir,
        app_path=app_path,
        python_executable="/venv/bin/python",
        runner=runner,
        helper_builder=_fake_helper_builder,
    )

    assert result == app_path
    assert [
        "osascript",
        "-e",
        f'tell application id "{BUNDLE_IDENTIFIER}" to quit',
    ] in [call[0] for call in calls]
    assert ["ps", "-ax", "-o", "pid=,args="] in [call[0] for call in calls]
    assert calls[-1] == (["open", str(app_path)], True)


def test_macos_app_executable_runs_project_module(tmp_path: Path) -> None:
    script = macos_app_executable(tmp_path, "/venv/bin/python")

    assert f"cd {tmp_path}" in script
    assert f"export PYTHONPATH={tmp_path / 'src'}" in script
    assert "MEETING_MEMORY_CAPTURE_HELPER" in script
    assert "MeetingMemoryCapture" in script
    assert "/venv/bin/python -m meeting_memory" in script
    assert "exec /venv/bin/python -m meeting_memory" not in script

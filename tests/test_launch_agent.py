"""Tests for macOS LaunchAgent installation helpers."""

from __future__ import annotations

import plistlib
from pathlib import Path

from meeting_memory.repo.native_audio_build import ENCODER_NAME
from meeting_memory.service.launch_agent import (
    LABEL,
    install_launch_agent,
    launch_agent_plist,
    uninstall_launch_agent,
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


def test_launch_agent_plist_opens_app_bundle(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    app_path = tmp_path / "Applications" / "Meeting Memory.app"

    plist = launch_agent_plist(tmp_path, app_path, tmp_path / "logs")

    assert plist["Label"] == LABEL
    assert plist["ProgramArguments"] == ["/usr/bin/open", "-gj", str(app_path)]
    assert plist["WorkingDirectory"] == str(tmp_path)
    assert "PYTHONPATH" not in plist["EnvironmentVariables"]
    assert plist["RunAtLoad"] is True
    assert plist["ProcessType"] == "Background"


def test_install_launch_agent_writes_plist_and_reloads(tmp_path: Path) -> None:
    calls = []
    plist_path = tmp_path / "LaunchAgents" / "com.meeting-memory.app.plist"
    app_path = tmp_path / "Applications" / "Meeting Memory.app"

    def runner(args, check):
        calls.append((args, check))

    result = install_launch_agent(
        project_dir=tmp_path,
        plist_path=plist_path,
        app_path=app_path,
        python_executable="/usr/bin/python3",
        runner=runner,
        helper_builder=_fake_helper_builder,
        uid=501,
    )

    plist = plistlib.loads(result.read_bytes())
    launchctl_calls = [call for call in calls if call[0][0] == "launchctl"]
    assert result == plist_path
    assert plist["Label"] == LABEL
    assert plist["ProgramArguments"] == ["/usr/bin/open", "-gj", str(app_path)]
    assert (app_path / "Contents" / "MacOS" / "Meeting Memory").exists()
    assert launchctl_calls[0][0][:2] == ["launchctl", "bootout"]
    assert launchctl_calls[1][0][:2] == ["launchctl", "bootstrap"]
    assert launchctl_calls[1][1] is True


def test_uninstall_launch_agent_boots_out_and_removes_plist(tmp_path: Path) -> None:
    calls = []
    plist_path = tmp_path / "agent.plist"
    plist_path.write_text("placeholder", encoding="utf-8")

    def runner(args, check):
        calls.append((args, check))

    result = uninstall_launch_agent(plist_path=plist_path, runner=runner, uid=501)

    assert result == plist_path
    assert not plist_path.exists()
    assert calls == [(["launchctl", "bootout", "gui/501", str(plist_path)], False)]

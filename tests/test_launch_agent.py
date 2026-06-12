"""Tests for macOS LaunchAgent installation helpers."""

from __future__ import annotations

import plistlib
from pathlib import Path

from meeting_memory.service.launch_agent import (
    LABEL,
    install_launch_agent,
    launch_agent_plist,
    uninstall_launch_agent,
)


def test_launch_agent_plist_uses_project_working_directory(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()

    plist = launch_agent_plist(tmp_path, "/usr/bin/python3", tmp_path / "logs")

    assert plist["Label"] == LABEL
    assert plist["ProgramArguments"] == ["/usr/bin/python3", "-m", "meeting_memory"]
    assert plist["WorkingDirectory"] == str(tmp_path)
    assert plist["EnvironmentVariables"]["PYTHONPATH"] == str(tmp_path / "src")
    assert plist["RunAtLoad"] is True
    assert plist["ProcessType"] == "Background"


def test_install_launch_agent_writes_plist_and_reloads(tmp_path: Path) -> None:
    calls = []
    plist_path = tmp_path / "LaunchAgents" / "com.meeting-memory.app.plist"

    def runner(args, check):
        calls.append((args, check))

    result = install_launch_agent(
        project_dir=tmp_path,
        plist_path=plist_path,
        python_executable="/usr/bin/python3",
        runner=runner,
        uid=501,
    )

    plist = plistlib.loads(result.read_bytes())
    assert result == plist_path
    assert plist["Label"] == LABEL
    assert calls[0][0][:2] == ["launchctl", "bootout"]
    assert calls[1][0][:2] == ["launchctl", "bootstrap"]
    assert calls[1][1] is True


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

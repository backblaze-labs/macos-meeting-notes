"""Install and remove the macOS LaunchAgent for Meeting Memory."""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from meeting_memory.repo.native_audio import build_native_capture_helper
from meeting_memory.service.macos_app import (
    HelperBuilder,
    default_app_path,
    install_macos_app,
)

LABEL = "com.meeting-memory.app"
PLIST_NAME = f"{LABEL}.plist"
DEFAULT_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

Runner = Callable[..., subprocess.CompletedProcess]


def install_launch_agent(
    *,
    project_dir: Path,
    plist_path: Path | None = None,
    app_path: Path | None = None,
    python_executable: str | None = None,
    runner: Runner = subprocess.run,
    helper_builder: HelperBuilder = build_native_capture_helper,
    uid: int | None = None,
) -> Path:
    target = plist_path or default_plist_path()
    root = project_dir.resolve()
    app_target = app_path or default_app_path()
    python = python_executable or sys.executable
    target.parent.mkdir(parents=True, exist_ok=True)
    log_dir = Path.home() / "Library" / "Logs" / "meeting-memory"
    log_dir.mkdir(parents=True, exist_ok=True)
    install_macos_app(
        project_dir=root,
        app_path=app_target,
        python_executable=python,
        runner=runner,
        helper_builder=helper_builder,
    )
    target.write_bytes(plistlib.dumps(launch_agent_plist(root, app_target, log_dir)))
    reload_launch_agent(target, runner=runner, uid=uid)
    return target


def uninstall_launch_agent(
    *,
    plist_path: Path | None = None,
    runner: Runner = subprocess.run,
    uid: int | None = None,
) -> Path:
    target = plist_path or default_plist_path()
    unload_launch_agent(target, runner=runner, uid=uid)
    target.unlink(missing_ok=True)
    return target


def launch_agent_plist(project_dir: Path, app_path: Path, log_dir: Path) -> dict[str, Any]:
    environment = {
        "PATH": DEFAULT_PATH,
        "PYTHONUNBUFFERED": "1",
    }

    return {
        "Label": LABEL,
        "ProgramArguments": ["/usr/bin/open", "-gj", str(app_path)],
        "WorkingDirectory": str(project_dir),
        "EnvironmentVariables": environment,
        "RunAtLoad": True,
        "KeepAlive": False,
        "ProcessType": "Background",
        "StandardOutPath": str(log_dir / "launch-agent.out.log"),
        "StandardErrorPath": str(log_dir / "launch-agent.err.log"),
    }


def reload_launch_agent(
    plist_path: Path,
    *,
    runner: Runner = subprocess.run,
    uid: int | None = None,
) -> None:
    unload_launch_agent(plist_path, runner=runner, uid=uid)
    domain = f"gui/{uid if uid is not None else os.getuid()}"
    runner(["launchctl", "bootstrap", domain, str(plist_path)], check=True)
    runner(["launchctl", "kickstart", "-k", f"{domain}/{LABEL}"], check=False)


def unload_launch_agent(
    plist_path: Path,
    *,
    runner: Runner = subprocess.run,
    uid: int | None = None,
) -> None:
    domain = f"gui/{uid if uid is not None else os.getuid()}"
    runner(["launchctl", "bootout", domain, str(plist_path)], check=False)


def default_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / PLIST_NAME

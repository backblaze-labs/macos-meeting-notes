"""Install and reload the clickable macOS app bundle."""

from __future__ import annotations

import os
import plistlib
import shlex
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from importlib.resources import as_file, files
from pathlib import Path
from typing import Any

from meeting_memory.repo.native_audio import (
    HELPER_NAME,
    build_native_capture_helper,
    default_build_helper_path,
)
from meeting_memory.repo.native_layout import HELPER_ENV_VAR

APP_NAME = "Meeting Memory"
APP_BUNDLE_NAME = f"{APP_NAME}.app"
BUNDLE_IDENTIFIER = "com.meeting-memory.app"
EXECUTABLE_NAME = APP_NAME
APP_ICON_FILE = "MeetingMemory.icns"
DEFAULT_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
LSREGISTER = (
    "/System/Library/Frameworks/CoreServices.framework/Frameworks/"
    "LaunchServices.framework/Support/lsregister"
)

Runner = Callable[..., subprocess.CompletedProcess]
HelperBuilder = Callable[..., Path]


def install_macos_app(
    *,
    project_dir: Path,
    app_path: Path | None = None,
    python_executable: str | None = None,
    runner: Runner = subprocess.run,
    helper_builder: HelperBuilder = build_native_capture_helper,
) -> Path:
    target = app_path or default_app_path()
    root = project_dir.resolve()
    contents = target / "Contents"
    macos_dir = contents / "MacOS"
    resources_dir = contents / "Resources"
    macos_dir.mkdir(parents=True, exist_ok=True)
    resources_dir.mkdir(parents=True, exist_ok=True)
    copy_macos_app_icon(resources_dir)
    built_helper = helper_builder(
        root,
        default_build_helper_path(root),
        runner=runner,
    )
    shutil.copyfile(built_helper, macos_dir / HELPER_NAME)
    (macos_dir / HELPER_NAME).chmod(0o755)

    executable = macos_dir / EXECUTABLE_NAME
    executable.write_text(
        macos_app_executable(root, python_executable or sys.executable),
        encoding="utf-8",
    )
    executable.chmod(0o755)
    (contents / "Info.plist").write_bytes(plistlib.dumps(macos_app_plist()))
    register_macos_app(target, runner=runner)
    return target


def reload_macos_app(
    *,
    project_dir: Path,
    app_path: Path | None = None,
    python_executable: str | None = None,
    runner: Runner = subprocess.run,
    helper_builder: HelperBuilder = build_native_capture_helper,
) -> Path:
    target = install_macos_app(
        project_dir=project_dir,
        app_path=app_path,
        python_executable=python_executable,
        runner=runner,
        helper_builder=helper_builder,
    )
    quit_macos_app(runner=runner)
    open_macos_app(target, runner=runner)
    return target


def macos_app_plist() -> dict[str, Any]:
    return {
        "CFBundleDevelopmentRegion": "en",
        "CFBundleDisplayName": APP_NAME,
        "CFBundleExecutable": EXECUTABLE_NAME,
        "CFBundleIconFile": APP_ICON_FILE,
        "CFBundleIdentifier": BUNDLE_IDENTIFIER,
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": APP_NAME,
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "1",
        "LSMinimumSystemVersion": "15.0",
        "LSUIElement": True,
        "NSMicrophoneUsageDescription": (
            "Meeting Memory records meeting audio when you start a recording."
        ),
        "NSScreenCaptureUsageDescription": (
            "Meeting Memory captures system audio only while you record a meeting."
        ),
        "NSPrincipalClass": "NSApplication",
    }


def macos_app_executable(project_dir: Path, python_executable: str) -> str:
    source_dir = project_dir / "src"
    pythonpath = shlex.quote(str(source_dir))
    project = shlex.quote(str(project_dir))
    python = shlex.quote(python_executable)
    return "\n".join(
        [
            "#!/bin/zsh",
            "set -e",
            f"cd {project}",
            f"export PATH={shlex.quote(DEFAULT_PATH)}",
            'export PYTHONUNBUFFERED="1"',
            f'export {HELPER_ENV_VAR}="${{0:A:h}}/{HELPER_NAME}"',
            f"export PYTHONPATH={pythonpath}${{PYTHONPATH:+:$PYTHONPATH}}",
            f"{python} -m meeting_memory",
            "",
        ]
    )


def copy_macos_app_icon(resources_dir: Path) -> None:
    destination = resources_dir / APP_ICON_FILE
    source_ref = files("meeting_memory.service.assets").joinpath(APP_ICON_FILE)
    with as_file(source_ref) as source:
        shutil.copyfile(source, destination)


def register_macos_app(app_path: Path, *, runner: Runner = subprocess.run) -> None:
    if Path(LSREGISTER).exists():
        runner([LSREGISTER, "-f", str(app_path)], check=False)


def quit_macos_app(*, runner: Runner = subprocess.run) -> None:
    script = f'tell application id "{BUNDLE_IDENTIFIER}" to quit'
    runner(["osascript", "-e", script], check=False)
    terminate_running_app_processes(runner=runner)


def open_macos_app(app_path: Path | None = None, *, runner: Runner = subprocess.run) -> None:
    target = app_path or default_app_path()
    runner(["open", str(target)], check=True)


def default_app_path() -> Path:
    return Path.home() / "Applications" / APP_BUNDLE_NAME


def user_applications_dir() -> Path:
    return Path.home() / "Applications"


def terminate_running_app_processes(*, runner: Runner = subprocess.run) -> None:
    result = runner(["ps", "-ax", "-o", "pid=,args="], check=False, capture_output=True, text=True)
    stdout = getattr(result, "stdout", "") or ""
    current_pid = os.getpid()
    for line in stdout.splitlines():
        pid, args = _parse_process_line(line)
        if pid is None or pid == current_pid or "-m meeting_memory" not in args:
            continue
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
    time.sleep(0.2)


def _parse_process_line(line: str) -> tuple[int | None, str]:
    stripped = line.strip()
    if not stripped:
        return None, ""
    pid_text, _, args = stripped.partition(" ")
    try:
        return int(pid_text), args
    except ValueError:
        return None, args

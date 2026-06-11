"""Zero-dependency preflight checks for meeting-memory."""

from __future__ import annotations

import os
import platform
import shutil
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from meeting_memory.config.defaults import (
    DEFAULT_AUDIO_DEVICE,
    DEFAULT_GOOGLE_CALENDAR_CREDENTIALS_FILE,
    PLACEHOLDER_MARKERS,
    REQUIRED_ENV_VARS,
)
from meeting_memory.repo.audio_device import AudioDeviceCheckUnavailable, list_audio_device_names

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    message: str
    fix: str | None = None
    warning: bool = False


def _read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def _configured_value(key: str, dotenv_values: dict[str, str]) -> str | None:
    return os.environ.get(key) or dotenv_values.get(key)


def _looks_placeholder(value: str) -> bool:
    normalized = value.strip().lower()
    return not normalized or any(marker in normalized for marker in PLACEHOLDER_MARKERS)


def check_python() -> CheckResult:
    if sys.version_info >= (3, 11):
        return CheckResult("python", True, f"Python {platform.python_version()} is supported.")
    return CheckResult(
        "python",
        False,
        "Python 3.11 or newer is required.",
        "Install Python 3.11+.",
    )


def check_macos() -> CheckResult:
    if platform.system() != "Darwin":
        return CheckResult(
            "macos",
            False,
            "meeting-memory targets macOS 13 or newer.",
            "Run on macOS.",
        )

    major = int(platform.release().split(".", maxsplit=1)[0])
    if major >= 22:
        return CheckResult("macos", True, "macOS version is supported.")
    return CheckResult(
        "macos",
        False,
        "macOS 13 Ventura or newer is required.",
        "Upgrade macOS before using recording features.",
    )


def check_env_file() -> CheckResult:
    if ENV_FILE.exists():
        return CheckResult("env-file", True, ".env exists.")
    return CheckResult(
        "env-file",
        False,
        ".env is missing.",
        "Copy .env.example to .env and fill in real values.",
    )


def check_required_env(dotenv_values: dict[str, str]) -> CheckResult:
    missing_or_placeholder = [
        key
        for key in REQUIRED_ENV_VARS
        if _looks_placeholder(_configured_value(key, dotenv_values) or "")
    ]
    if not missing_or_placeholder:
        return CheckResult("required-env", True, "Required environment values are present.")

    missing = ", ".join(missing_or_placeholder)
    return CheckResult(
        "required-env",
        False,
        f"Missing or placeholder values: {missing}.",
        "Set these keys in .env or the process environment.",
    )


def check_ffmpeg() -> CheckResult:
    if shutil.which("ffmpeg"):
        return CheckResult("ffmpeg", True, "ffmpeg is available on PATH.")
    return CheckResult("ffmpeg", False, "ffmpeg was not found on PATH.", "Install ffmpeg.")


def check_google_credentials(dotenv_values: dict[str, str]) -> CheckResult:
    configured = _configured_value(
        "GOOGLE_CALENDAR_CREDENTIALS_FILE",
        dotenv_values,
    ) or DEFAULT_GOOGLE_CALENDAR_CREDENTIALS_FILE
    path = Path(configured).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    if path.exists():
        return CheckResult("google-credentials", True, f"Found Google credentials at {path}.")
    return CheckResult(
        "google-credentials",
        False,
        f"Google OAuth credentials file is missing: {path}.",
        "Download OAuth client credentials and update GOOGLE_CALENDAR_CREDENTIALS_FILE.",
    )


def check_audio_device(dotenv_values: dict[str, str]) -> CheckResult:
    configured = _configured_value("AUDIO_DEVICE", dotenv_values) or DEFAULT_AUDIO_DEVICE
    try:
        device_names = list_audio_device_names()
    except AudioDeviceCheckUnavailable as exc:
        return CheckResult("audio-device", True, str(exc), "Install dependencies.", warning=True)

    if configured in device_names:
        return CheckResult("audio-device", True, f"Audio device exists: {configured}.")
    return CheckResult(
        "audio-device",
        False,
        f"Audio device was not found: {configured}.",
        "Create the aggregate device or set AUDIO_DEVICE in .env.",
    )


def run_checks() -> list[CheckResult]:
    dotenv_values = _read_dotenv(ENV_FILE)
    return [
        check_python(),
        check_macos(),
        check_env_file(),
        check_required_env(dotenv_values),
        check_ffmpeg(),
        check_google_credentials(dotenv_values),
        check_audio_device(dotenv_values),
    ]


def render_results(results: Iterable[CheckResult]) -> str:
    lines: list[str] = []
    for result in results:
        status = "WARN" if result.warning else "OK" if result.ok else "FAIL"
        lines.append(f"[{status}] {result.name}: {result.message}")
        if result.fix and (result.warning or not result.ok):
            lines.append(f"      fix: {result.fix}")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    results = run_checks()
    sys.stdout.write(render_results(results))
    return 1 if any(not result.ok and not result.warning for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())

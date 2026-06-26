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
    ASSEMBLYAI_ENV_VARS,
    B2_ENV_VARS,
    DEFAULT_AUDIO_DEVICE,
    DEFAULT_GOOGLE_CALENDAR_CREDENTIALS_FILE,
    PLACEHOLDER_MARKERS,
)
from meeting_memory.repo.audio_device import (
    AudioDeviceCheckUnavailable,
    AudioDeviceInfo,
    list_audio_devices,
)

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


def _missing_or_placeholder(keys: Iterable[str], dotenv_values: dict[str, str]) -> list[str]:
    return [
        key
        for key in keys
        if _looks_placeholder(_configured_value(key, dotenv_values) or "")
    ]


def check_b2_env(dotenv_values: dict[str, str]) -> CheckResult:
    missing_or_placeholder = _missing_or_placeholder(B2_ENV_VARS, dotenv_values)
    if not missing_or_placeholder:
        return CheckResult("b2-env", True, "Required B2 values are present.")

    missing = ", ".join(missing_or_placeholder)
    return CheckResult(
        "b2-env",
        False,
        f"Missing or placeholder B2 values: {missing}.",
        "Create a dedicated B2 bucket/key and set these keys in .env.",
    )


def check_assemblyai_env(dotenv_values: dict[str, str]) -> CheckResult:
    missing_or_placeholder = _missing_or_placeholder(ASSEMBLYAI_ENV_VARS, dotenv_values)
    if not missing_or_placeholder:
        return CheckResult("assemblyai-env", True, "AssemblyAI API key is present.")

    missing = ", ".join(missing_or_placeholder)
    return CheckResult(
        "assemblyai-env",
        False,
        f"Missing or placeholder values: {missing}.",
        "Set ASSEMBLYAI_API_KEY in .env.",
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


def check_google_token() -> CheckResult:
    try:
        token_store_cls = _keychain_token_store_cls()
    except ModuleNotFoundError as exc:
        return CheckResult(
            "google-token",
            True,
            f"{exc.name} is not installed; could not verify Google auth token.",
            "Run make setup, then .venv/bin/meeting-memory auth.",
            warning=True,
        )

    try:
        token = token_store_cls().read_token()
    except Exception as exc:  # pragma: no cover - keychain availability is local.
        return CheckResult(
            "google-token",
            True,
            f"Could not read Google token from Keychain: {exc}.",
            "Run .venv/bin/meeting-memory auth after dependencies are installed.",
            warning=True,
        )

    if token:
        return CheckResult("google-token", True, "Google Calendar token exists in Keychain.")
    return CheckResult(
        "google-token",
        False,
        "Google Calendar has not been authorized.",
        "Run .venv/bin/meeting-memory auth.",
    )


def _keychain_token_store_cls():
    from meeting_memory.repo.calendar_client import KeychainTokenStore

    return KeychainTokenStore


def check_audio_device(dotenv_values: dict[str, str]) -> CheckResult:
    configured = _configured_value("AUDIO_DEVICE", dotenv_values) or DEFAULT_AUDIO_DEVICE
    try:
        devices = list_audio_devices()
    except AudioDeviceCheckUnavailable as exc:
        return CheckResult("audio-device", True, str(exc), "Install dependencies.", warning=True)

    input_devices = [device for device in devices if device.max_input_channels > 0]
    if not input_devices:
        return CheckResult(
            "audio-device",
            True,
            (
                "No audio input devices are visible to this process; "
                f"could not verify AUDIO_DEVICE={configured}."
            ),
            (
                "Grant microphone access to the terminal or run diagnostics from "
                "Meeting Memory.app. If the app records successfully, the aggregate "
                "device is likely OK."
            ),
            warning=True,
        )

    matching_devices = [device for device in input_devices if device.name == configured]
    if matching_devices:
        return CheckResult("audio-device", True, f"Audio device exists: {configured}.")

    if any(device.name == configured for device in devices):
        return CheckResult(
            "audio-device",
            False,
            f"Audio device exists but has no input channels: {configured}.",
            "Use an aggregate/input device that exposes microphone or BlackHole input channels.",
        )

    visible = _format_audio_devices(input_devices)
    return CheckResult(
        "audio-device",
        False,
        f"Audio input device was not found: {configured}. Visible input devices: {visible}.",
        "Create the aggregate device or set AUDIO_DEVICE in .env.",
    )


def _format_audio_devices(devices: Sequence[AudioDeviceInfo], limit: int = 8) -> str:
    visible = [f"{device.name} ({device.max_input_channels} in)" for device in devices[:limit]]
    if len(devices) > limit:
        visible.append(f"{len(devices) - limit} more")
    return ", ".join(visible)


def run_checks() -> list[CheckResult]:
    dotenv_values = _read_dotenv(ENV_FILE)
    return [
        check_python(),
        check_macos(),
        check_env_file(),
        check_b2_env(dotenv_values),
        check_assemblyai_env(dotenv_values),
        check_ffmpeg(),
        check_google_credentials(dotenv_values),
        check_google_token(),
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

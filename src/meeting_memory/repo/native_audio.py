"""Adapter for the native macOS meeting-audio capture helper."""

from __future__ import annotations

import json
import os
import platform
import queue
import shutil
import signal
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

HELPER_ENV_VAR = "MEETING_MEMORY_CAPTURE_HELPER"
HELPER_NAME = "MeetingMemoryCapture"
BUILD_DIR_NAME = ".build"
START_TIMEOUT_SECONDS = 60
STOP_TIMEOUT_SECONDS = 20

Runner = Callable[..., subprocess.CompletedProcess]


class NativeAudioCaptureError(RuntimeError):
    """Raised when native audio capture cannot start or finish."""


@dataclass
class NativeCaptureProcess:
    process: subprocess.Popen[str]
    output_path: Path
    events: queue.Queue[dict[str, Any]]
    reader: threading.Thread

    def stop(self) -> Path:
        if self.process.poll() is None:
            self.process.send_signal(signal.SIGINT)
        try:
            return_code = self.process.wait(timeout=STOP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as exc:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
            raise NativeAudioCaptureError("Native audio capture did not stop cleanly.") from exc

        self.reader.join(timeout=2)
        errors = _captured_errors(self.events)
        if return_code != 0:
            detail = errors[-1] if errors else f"helper exited with status {return_code}"
            raise NativeAudioCaptureError(f"Native audio capture failed: {detail}")
        if not self.output_path.exists() or self.output_path.stat().st_size <= 44:
            detail = errors[-1] if errors else "no audio samples were written"
            raise NativeAudioCaptureError(f"Native audio capture produced no audio: {detail}")
        return self.output_path


def start_native_capture(mode_key: str, output_path: Path) -> NativeCaptureProcess:
    helper = native_capture_helper_path()
    process = subprocess.Popen(
        [str(helper), "record", mode_key, "--output", str(output_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    events: queue.Queue[dict[str, Any]] = queue.Queue()
    reader = threading.Thread(
        target=_read_helper_output,
        args=(process.stdout, process.stderr, events),
        daemon=True,
    )
    reader.start()

    try:
        event = events.get(timeout=START_TIMEOUT_SECONDS)
    except queue.Empty as exc:
        process.terminate()
        process.wait(timeout=5)
        raise NativeAudioCaptureError(
            "Native audio capture timed out. Check Microphone and "
            "Screen & System Audio permissions."
        ) from exc

    if event.get("event") != "ready":
        process.terminate()
        process.wait(timeout=5)
        message = str(event.get("message") or "native capture could not start")
        raise NativeAudioCaptureError(message)
    return NativeCaptureProcess(process, output_path, events, reader)


def check_native_capture() -> dict[str, Any]:
    helper = native_capture_helper_path()
    result = subprocess.run(
        [str(helper), "check"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    events = [_parse_event(line) for line in result.stdout.splitlines()]
    event = next((item for item in events if item), None)
    if result.returncode != 0 or not event or event.get("event") != "supported":
        message = str((event or {}).get("message") or result.stderr.strip() or "check failed")
        raise NativeAudioCaptureError(message)
    return event


def convert_native_audio(wav_path: Path, m4a_path: Path) -> Path:
    helper = native_capture_helper_path()
    result = subprocess.run(
        [str(helper), "convert", str(wav_path), "--output", str(m4a_path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    events = [_parse_event(line) for line in result.stdout.splitlines()]
    event = next((item for item in events if item), None)
    if result.returncode != 0 or not event or event.get("event") != "converted":
        message = str((event or {}).get("message") or result.stderr.strip() or "conversion failed")
        raise NativeAudioCaptureError(f"Native audio conversion failed: {message}")
    if not m4a_path.exists() or m4a_path.stat().st_size == 0:
        raise NativeAudioCaptureError("Native audio conversion produced no output.")
    return m4a_path


def native_capture_helper_path() -> Path:
    configured = os.environ.get(HELPER_ENV_VAR)
    candidates = [
        Path(configured).expanduser() if configured else None,
        Path.cwd() / BUILD_DIR_NAME / HELPER_NAME,
    ]
    for candidate in candidates:
        if candidate is not None and candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise NativeAudioCaptureError(
        "Native audio helper is missing. Run make setup or make install-macos-app."
    )


def build_native_capture_helper(
    project_dir: Path,
    output_path: Path,
    *,
    runner: Runner = subprocess.run,
) -> Path:
    source_dir = project_dir / "src" / "meeting_memory" / "repo" / "native"
    sources = sorted(source_dir.glob("*.swift"))
    if not sources:
        raise NativeAudioCaptureError(f"Native capture sources are missing: {source_dir}")
    swiftc = shutil.which("swiftc")
    if swiftc is None:
        raise NativeAudioCaptureError(
            "Swift compiler is missing. Install Xcode Command Line Tools with "
            "xcode-select --install."
        )
    sdk_path = _compatible_sdk_path()
    architecture = "x86_64" if platform.machine() == "x86_64" else "arm64"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    module_cache = output_path.parent / "swift-module-cache"
    module_cache.mkdir(parents=True, exist_ok=True)
    command: list[str] = [
        swiftc,
        "-O",
        "-module-cache-path",
        str(module_cache),
        "-sdk",
        str(sdk_path),
        "-target",
        f"{architecture}-apple-macosx15.0",
    ]
    for framework in ("AVFoundation", "CoreAudio", "CoreMedia", "ScreenCaptureKit"):
        command.extend(["-framework", framework])
    command.extend(str(path) for path in sources)
    command.extend(["-o", str(output_path)])
    try:
        runner(command, check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = str(getattr(exc, "stderr", "") or exc).strip()
        raise NativeAudioCaptureError(
            "Could not build the native audio helper. Install or update Xcode "
            f"Command Line Tools, then retry. Detail: {detail}"
        ) from exc
    if not output_path.is_file():
        raise NativeAudioCaptureError("Swift finished without creating the audio helper.")
    output_path.chmod(0o755)
    return output_path


def default_build_helper_path(project_dir: Path) -> Path:
    return project_dir / BUILD_DIR_NAME / HELPER_NAME


def _compatible_sdk_path() -> Path:
    sdk_root = Path("/Library/Developer/CommandLineTools/SDKs")
    macos_15_sdks = sorted(sdk_root.glob("MacOSX15*.sdk"), reverse=True)
    if macos_15_sdks:
        return macos_15_sdks[0]
    result = subprocess.run(
        ["xcrun", "--sdk", "macosx", "--show-sdk-path"],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(result.stdout.strip())


def _read_helper_output(
    stdout: TextIO | None,
    stderr: TextIO | None,
    events: queue.Queue[dict[str, Any]],
) -> None:
    if stdout is not None:
        for line in stdout:
            if event := _parse_event(line):
                events.put(event)
    if stderr is not None:
        detail = stderr.read().strip()
        if detail:
            events.put({"event": "error", "message": detail})


def _parse_event(line: str) -> dict[str, Any] | None:
    try:
        value = json.loads(line)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _captured_errors(events: queue.Queue[dict[str, Any]]) -> list[str]:
    drained: list[dict[str, Any]] = []
    while True:
        try:
            drained.append(events.get_nowait())
        except queue.Empty:
            break
    return [
        str(event.get("message"))
        for event in drained
        if event.get("event") in {"error", "fatal"} and event.get("message")
    ]

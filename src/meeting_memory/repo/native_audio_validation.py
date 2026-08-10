"""Strong native validation for committed or recovered M4A/AAC audio."""

from __future__ import annotations

import fcntl
import json
import os
import stat
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from meeting_memory.repo.native_audio import (
    NativeAudioCaptureError,
    native_capture_helper_path,
)

Runner = Callable[..., subprocess.CompletedProcess[str]]
NATIVE_VALIDATION_TIMEOUT_SECONDS = 30


def validate_native_m4a(
    path: Path,
    *,
    runner: Runner = subprocess.run,
) -> None:
    """Require a readable M4A container with AAC packets and positive duration."""

    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        inherited = _inherited_descriptor(path)
        visible = os.fstat(inherited) if inherited is not None else os.stat(
            path,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_size == 0
            or (info.st_dev, info.st_ino) != (visible.st_dev, visible.st_ino)
            or (
                inherited is not None
                and fcntl.fcntl(inherited, fcntl.F_GETFL) & os.O_ACCMODE
                != os.O_RDONLY
            )
        ):
            raise NativeAudioCaptureError("M4A input must be a non-empty regular file")
    finally:
        os.close(descriptor)
    helper = native_capture_helper_path()
    try:
        result = _run_validation(helper, path, runner)
    except subprocess.TimeoutExpired as exc:
        raise NativeAudioCaptureError("native M4A validation timed out") from exc
    events = _events(result.stdout)
    fatal = next((event for event in events if event.get("event") == "fatal"), None)
    validated_events = tuple(event for event in events if event.get("event") == "validated")
    validated = validated_events[0] if len(validated_events) == 1 and len(events) == 1 else None
    if result.returncode != 0 or fatal is not None or validated is None:
        detail = (
            str((fatal or {}).get("message") or "").strip()
            or result.stderr.strip()
            or "native M4A validation failed"
        )
        raise NativeAudioCaptureError(detail)
    if (
        validated.get("codec") != "aac"
        or int(validated.get("packets") or 0) <= 0
        or float(validated.get("duration_seconds") or 0) <= 0
        or float(validated.get("sample_rate") or 0) != 16_000
        or int(validated.get("channels") or 0) != 1
    ):
        raise NativeAudioCaptureError("native M4A validation returned invalid audio facts")


def _events(output: str) -> tuple[dict[str, object], ...]:
    parsed: list[dict[str, object]] = []
    for line in output.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            parsed.append(value)
    return tuple(parsed)


def _run_validation(
    helper: Path,
    path: Path,
    runner: Runner,
) -> subprocess.CompletedProcess[str]:
    descriptor = _inherited_descriptor(path)
    if descriptor is None:
        return _run_command(runner, [str(helper), "validate", str(path)])
    with tempfile.TemporaryDirectory(prefix="meeting-memory-validation-") as raw_dir:
        return _run_command(
            runner,
            [str(helper), "validate-fd", str(descriptor), raw_dir],
            pass_fds=(descriptor,),
        )


def _run_command(
    runner: Runner,
    command: list[str],
    *,
    pass_fds: tuple[int, ...] = (),
) -> subprocess.CompletedProcess[str]:
    return runner(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=NATIVE_VALIDATION_TIMEOUT_SECONDS,
        pass_fds=pass_fds,
    )


def _inherited_descriptor(path: Path) -> int | None:
    if path.parent != Path("/dev/fd") or not path.name.isdecimal():
        return None
    return int(path.name)

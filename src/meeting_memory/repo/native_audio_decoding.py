"""Private native PCM decoding from a stable read-only audio snapshot."""

from __future__ import annotations

import fcntl
import json
import math
import os
import stat
import subprocess
import tempfile
import time
import wave
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

from meeting_memory.repo.native_audio import NativeAudioCaptureError, native_capture_helper_path

DECODE_TIMEOUT_SECONDS = 120


@contextmanager
def decoded_native_audio(
    audio: BinaryIO,
    *,
    helper: Path | None = None,
    cancelled: Callable[[], bool] = lambda: False,
    timeout_seconds: float = DECODE_TIMEOUT_SECONDS,
    operation_lock_fd: int | None = None,
) -> Iterator[Path]:
    """Yield private 16 kHz mono s16 PCM; never reopen the meeting's audio path."""

    descriptor = audio.fileno()
    info = os.fstat(descriptor)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_size <= 0
        or fcntl.fcntl(descriptor, fcntl.F_GETFL) & os.O_ACCMODE != os.O_RDONLY
    ):
        raise NativeAudioCaptureError("Local decoding requires a read-only audio snapshot.")
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("decode timeout must be positive")
    if cancelled():
        raise NativeAudioCaptureError("Local audio decoding was cancelled.")
    with tempfile.TemporaryDirectory(prefix="meeting-memory-decoding-") as raw_directory:
        directory = Path(raw_directory)
        try:
            process = subprocess.Popen(
                [
                    str(helper or native_capture_helper_path()),
                    "decode-fd",
                    str(descriptor),
                    raw_directory,
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                close_fds=True,
                pass_fds=(descriptor,)
                if operation_lock_fd is None
                else (descriptor, operation_lock_fd),
                env={
                    "PATH": "/usr/bin:/bin",
                    "LANG": "C",
                    "LC_ALL": "C",
                    "MEETING_MEMORY_DECODE_PARENT_PID": str(os.getpid()),
                },
            )
        except OSError:
            raise NativeAudioCaptureError(
                "The local audio decoder could not start. Reinstall Meeting Memory and retry."
            ) from None
        try:
            output = _wait_for_decode(process, cancelled, timeout_seconds)
            path = directory / "decoded.wav"
            _validate_decode(path, output)
            yield path
        finally:
            _stop_decoder(process)


def _wait_for_decode(
    process: subprocess.Popen[str],
    cancelled: Callable[[], bool],
    timeout_seconds: float,
) -> str:
    deadline = time.monotonic() + timeout_seconds
    while True:
        if cancelled():
            raise NativeAudioCaptureError("Local audio decoding was cancelled.")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise NativeAudioCaptureError("Local audio decoding timed out. Retry the recording.")
        try:
            output, _stderr = process.communicate(timeout=min(0.1, remaining))
            break
        except subprocess.TimeoutExpired:
            continue
    if process.returncode != 0:
        raise NativeAudioCaptureError("Local audio could not be decoded. Retry the recording.")
    return output


def _stop_decoder(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    for stream in (process.stdout, process.stderr):
        if stream is not None:
            stream.close()


def _validate_decode(path: Path, output: str) -> None:
    try:
        events = [json.loads(line) for line in output.splitlines()]
        if len(events) != 1 or not isinstance(events[0], dict):
            raise ValueError("unexpected helper output")
        event = events[0]
        frames = event.get("frames")
        if (
            event.get("event") != "decoded"
            or event.get("sample_rate") != 16_000
            or event.get("channels") != 1
            or not isinstance(frames, int)
            or isinstance(frames, bool)
            or frames <= 0
        ):
            raise ValueError("invalid decoded audio facts")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or frames > info.st_size // 2:
                raise ValueError("invalid PCM file")
            os.fchmod(stream.fileno(), 0o600)
            with wave.open(stream, "rb") as pcm:
                if (pcm.getframerate(), pcm.getnchannels(), pcm.getsampwidth()) != (16_000, 1, 2):
                    raise ValueError("invalid PCM format")
                if pcm.getnframes() != frames:
                    raise ValueError("PCM frame count differs")
                pcm.setpos(frames - 1)
                if len(pcm.readframes(1)) != 2:
                    raise ValueError("truncated PCM file")
    except (OSError, ValueError, TypeError, wave.Error, EOFError):
        raise NativeAudioCaptureError(
            "Decoded local audio could not be verified. Retry it."
        ) from None

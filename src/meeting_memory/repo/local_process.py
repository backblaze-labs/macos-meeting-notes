"""Cancellable private worker processes with no inherited provider credentials."""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import queue
import stat
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

from meeting_memory.repo.local_worker_lifetime import LOCK_FD_ENV, PARENT_PID_ENV, TEMP_ROOT_ENV
from meeting_memory.types.local_transcription import (
    LocalModelProgress,
    LocalTranscriptionCancelled,
    LocalTranscriptionError,
)

ProgressSink = Callable[[LocalModelProgress], None]
Cancelled = Callable[[], bool]
PHASES = {
    "waiting": "Waiting for the other local model operation to finish.",
    "checking": "Checking the downloaded local models.",
    "downloading": "Downloading local models from Hugging Face. No meeting content is sent.",
    "decoding": "Preparing local audio.",
    "loading-transcription": "Loading the local transcription model.",
    "transcribing": "Transcribing on this Mac.",
    "loading-diarization": "Loading the local speaker diarization model.",
    "diarizing": "Separating speakers on this Mac.",
    "ready": "Local models are ready.",
}


def child_environment(*, offline: bool) -> dict[str, str]:
    """Do not copy the parent's environment, API keys, tokens, proxy, or Python hooks."""

    environment = {
        "HOME": str(Path.home()),
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "LANG": "en_US.UTF-8",
        "PYTHONUTF8": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
        "HF_HUB_DISABLE_XET": "1",
        "DO_NOT_TRACK": "1",
        "TOKENIZERS_PARALLELISM": "false",
        PARENT_PID_ENV: str(os.getpid()),
        TEMP_ROOT_ENV: str(Path(tempfile.gettempdir()).resolve()),
    }
    if not getattr(sys, "frozen", False):
        environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
    if offline:
        environment.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    return environment


@contextlib.contextmanager
def local_operation_lock(
    *, progress: ProgressSink, cancelled: Cancelled, lock_path: Path | None = None
) -> Iterator[int]:
    path = lock_path or (
        Path.home() / "Library/Application Support/meeting-memory/local-models.lock"
    )
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError("unsafe local model lock")
        announced = False
        while True:
            if cancelled():
                raise LocalTranscriptionCancelled()
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if not announced:
                    progress(LocalModelProgress("waiting", PHASES["waiting"]))
                    announced = True
                time.sleep(0.1)
        yield fd
    finally:
        os.close(fd)


def _read_events(stream, events: queue.Queue) -> None:
    try:
        while line := stream.readline(4097):
            if len(line) > 4096:
                continue
            try:
                row = json.loads(line)
                events.put_nowait(row)
            except (ValueError, queue.Full):
                continue
    finally:
        stream.close()


def run_local_worker(
    request: Path,
    *,
    offline: bool,
    progress: ProgressSink,
    cancelled: Cancelled,
    timeout_seconds: float = 3600,
    lock_fd: int | None = None,
    on_started: Callable[[subprocess.Popen], None] = lambda _process: None,
    on_stopped: Callable[[subprocess.Popen], None] = lambda _process: None,
) -> None:
    if cancelled():
        raise LocalTranscriptionCancelled()
    command = (
        [sys.executable, "local-model-worker", str(request)]
        if getattr(sys, "frozen", False)
        else [sys.executable, "-m", "meeting_memory.repo.local_worker", str(request)]
    )
    environment = child_environment(offline=offline)
    if lock_fd is not None:
        environment[LOCK_FD_ENV] = str(lock_fd)
    process = subprocess.Popen(
        command,
        env=environment,
        pass_fds=() if lock_fd is None else (lock_fd,),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        text=True,
        start_new_session=True,
    )
    events: queue.Queue = queue.Queue(maxsize=128)
    reader = threading.Thread(target=_read_events, args=(process.stdout, events), daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout_seconds
    try:
        on_started(process)
        while True:
            if cancelled():
                raise LocalTranscriptionCancelled()
            if time.monotonic() >= deadline:
                raise LocalTranscriptionError(
                    "The local model operation timed out.",
                    "Retry after closing other memory-intensive apps.",
                )
            try:
                row = events.get(timeout=0.1)
            except queue.Empty:
                row = None
            if isinstance(row, dict) and row.get("phase") in PHASES:
                phase = row["phase"]
                completed, total = row.get("completed_bytes"), row.get("total_bytes")
                if not (
                    isinstance(completed, int)
                    and isinstance(total, int)
                    and 0 <= completed <= total
                    and total > 0
                ):
                    completed = total = None
                progress(LocalModelProgress(phase, PHASES[phase], completed, total))
            if process.poll() is not None and events.empty():
                break
        if process.returncode == 3:
            raise LocalTranscriptionError(
                "The local backend cannot access Metal on this Mac.",
                "Run the native Apple Silicon app and check local backend readiness.",
            )
        if process.returncode:
            action = "Check disk space and your connection, then choose Prepare Local Models."
            if offline:
                action = "Check local model readiness, close other apps to free memory, and retry."
            raise LocalTranscriptionError("The local model operation could not complete.", action)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        reader.join(timeout=5)
        on_stopped(process)

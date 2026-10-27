"""Model preparation and cheap local-only readiness without loading MLX weights."""

from __future__ import annotations

import importlib.util
import json
import os
import platform
import tempfile
from pathlib import Path

from meeting_memory.repo.local_model_cache import cache_root, validate_models
from meeting_memory.repo.local_process import (
    PHASES,
    Cancelled,
    ProgressSink,
    local_operation_lock,
    run_local_worker,
)
from meeting_memory.types.local_transcription import (
    LocalBackendStatus,
    LocalModelProgress,
    LocalTranscriptionCancelled,
    LocalTranscriptionError,
)


def inspect_local_backend(
    *, cache: Path | None = None, probe_metal: bool = False, cancelled: Cancelled = lambda: False
) -> LocalBackendStatus:
    if cancelled():
        raise LocalTranscriptionCancelled()
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        return LocalBackendStatus(
            False,
            False,
            False,
            "Local transcription requires macOS on Apple Silicon with a native arm64 app.",
            "Use an Apple Silicon Mac, or explicitly configure AssemblyAI after its disclosure.",
        )
    if not all(importlib.util.find_spec(name) for name in ("mlx", "mlx_audio", "huggingface_hub")):
        return LocalBackendStatus(
            True,
            False,
            False,
            "The local transcription runtime is not installed.",
            "Reinstall or update Meeting Memory to restore its local transcription runtime.",
        )
    if probe_metal and not verify_local_runtime(cache=cache, cancelled=cancelled):
        return LocalBackendStatus(
            False,
            True,
            False,
            "The local backend cannot access Metal on this Mac.",
            "Run the native Apple Silicon app and retry the local setup check.",
        )
    try:
        validate_models(cache or cache_root(), hashes=False)
    except LocalTranscriptionError:
        return LocalBackendStatus(
            True,
            True,
            False,
            "Local transcription models need preparation.",
            "Choose Prepare Local Models. Recording remains available.",
        )
    return LocalBackendStatus(
        True,
        True,
        True,
        "Local transcription models are available.",
        "Models are verified before local processing starts.",
    )


def prepare_models(
    *,
    progress: ProgressSink = lambda _event: None,
    cancelled: Cancelled = lambda: False,
    cache: Path | None = None,
) -> None:
    status = inspect_local_backend(cache=cache)
    if not status.supported or not status.runtime_available:
        raise LocalTranscriptionError(status.summary, status.action)
    with local_operation_lock(progress=progress, cancelled=cancelled) as lock_fd:
        progress(LocalModelProgress("checking", PHASES["checking"]))
        selected_cache = cache or cache_root()
        try:
            validate_models(selected_cache)
        except LocalTranscriptionError:
            with tempfile.TemporaryDirectory(prefix="meeting-memory-models-") as directory:
                root = Path(directory)
                os.chmod(root, 0o700)
                request = root / "request.json"
                request.write_text(
                    json.dumps({"operation": "prepare", "cache": str(selected_cache)})
                )
                request.chmod(0o600)
                run_local_worker(
                    request, offline=False, progress=progress, cancelled=cancelled, lock_fd=lock_fd
                )
            validate_models(selected_cache)
        progress(LocalModelProgress("ready", PHASES["ready"]))


def verify_local_runtime(
    *, cache: Path | None = None, cancelled: Cancelled = lambda: False
) -> bool:
    """Bounded explicit readiness probe, in a child and without loading model weights."""

    try:
        with tempfile.TemporaryDirectory(prefix="meeting-memory-probe-") as directory:
            root = Path(directory)
            os.chmod(root, 0o700)
            request = root / "request.json"
            request.write_text(
                json.dumps({"operation": "probe", "cache": str(cache or cache_root())})
            )
            request.chmod(0o600)
            run_local_worker(
                request,
                offline=True,
                progress=lambda _: None,
                cancelled=cancelled,
                timeout_seconds=10,
            )
            value = json.loads((root / "result.json").read_text())
            return value == {"metal_available": True}
    except LocalTranscriptionCancelled:
        raise
    except (LocalTranscriptionError, OSError, ValueError):
        return False

"""Local transcription adapter preserving the existing readonly audio boundary."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import wave
from pathlib import Path
from typing import BinaryIO

from meeting_memory.repo.local_model_cache import cache_root, validate_models
from meeting_memory.repo.local_models import inspect_local_backend
from meeting_memory.repo.local_process import (
    PHASES,
    Cancelled,
    ProgressSink,
    local_operation_lock,
    run_local_worker,
)
from meeting_memory.repo.native_audio_decoding import decoded_native_audio
from meeting_memory.types.local_transcription import (
    ASRSegment,
    ASRWord,
    DiarizationTurn,
    LocalModelProgress,
    LocalModelsUnavailable,
    LocalTranscriptionCancelled,
    LocalTranscriptionError,
    LocalTranscriptionOutput,
)


class LocalTranscriptionClient:
    def __init__(self, *, helper: Path | None = None, cache: Path | None = None) -> None:
        self._helper = helper
        self._cache = cache or cache_root()
        self._closed = threading.Event()
        self._process_lock = threading.Lock()
        self._processes: set = set()

    def close(self) -> None:
        """Permanently cancel admission and signal active children without joining the UI."""

        self._closed.set()
        with self._process_lock:
            active = tuple(self._processes)
        for process in active:
            try:
                process.terminate()
            except OSError:
                # A child may already be gone; continue cancelling the other owned children.
                pass

    def _track_process(self, process) -> None:
        with self._process_lock:
            self._processes.add(process)
            closed = self._closed.is_set()
        if closed:
            process.terminate()

    def _forget_process(self, process) -> None:
        with self._process_lock:
            self._processes.discard(process)

    def transcribe(
        self,
        audio: BinaryIO,
        *,
        progress: ProgressSink = lambda _event: None,
        cancelled: Cancelled = lambda: False,
    ) -> LocalTranscriptionOutput:
        caller_cancelled = cancelled

        def cancelled() -> bool:
            return self._closed.is_set() or caller_cancelled()

        if cancelled():
            raise LocalTranscriptionCancelled()
        status = inspect_local_backend(cache=self._cache)
        if not status.supported or not status.runtime_available:
            raise LocalTranscriptionError(status.summary, status.action)
        if not status.models_ready:
            raise LocalModelsUnavailable(status.summary, status.action)
        with local_operation_lock(progress=progress, cancelled=cancelled) as lock_fd:
            progress(LocalModelProgress("checking", PHASES["checking"]))
            validate_models(self._cache)
            progress(LocalModelProgress("decoding", PHASES["decoding"]))
            with decoded_native_audio(
                audio, helper=self._helper, cancelled=cancelled, operation_lock_fd=lock_fd
            ) as pcm:
                with wave.open(str(pcm), "rb") as source:
                    duration = source.getnframes() / source.getframerate()
                with tempfile.TemporaryDirectory(prefix="meeting-memory-inference-") as directory:
                    root = Path(directory)
                    os.chmod(root, 0o700)
                    request = root / "request.json"
                    request.write_text(
                        json.dumps(
                            {"operation": "infer", "cache": str(self._cache), "audio": str(pcm)}
                        )
                    )
                    request.chmod(0o600)
                    run_local_worker(
                        request,
                        offline=True,
                        progress=progress,
                        cancelled=cancelled,
                        lock_fd=lock_fd,
                        on_started=self._track_process,
                        on_stopped=self._forget_process,
                    )
                    return read_local_output(root / "result.json", duration=duration)


def read_local_output(path: Path, *, duration: float) -> LocalTranscriptionOutput:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024 * 1024:
            raise ValueError("invalid output file")
        row = json.loads(path.read_text())
        if set(row) != {"segments", "turns", "language"}:
            raise ValueError("invalid output schema")
        if not isinstance(row["language"], str) or len(row["language"]) > 16:
            raise ValueError("invalid detected language")
        if len(row["segments"]) > 200000 or len(row["turns"]) > 200000:
            raise ValueError("excessive output")
        segments = []
        for item in row["segments"]:
            words = tuple(ASRWord(**word) for word in item.pop("words"))
            segments.append(ASRSegment(**item, words=words))
        return LocalTranscriptionOutput(
            tuple(segments),
            tuple(DiarizationTurn(**turn) for turn in row["turns"]),
            row["language"],
            duration,
        )
    except (OSError, TypeError, ValueError, KeyError):
        raise LocalTranscriptionError(
            "The local transcript output could not be validated.",
            "Your recording is preserved. Retry local transcription.",
        ) from None

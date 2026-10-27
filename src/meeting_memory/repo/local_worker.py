"""Private local-model worker; invoked only with an app-owned request document."""

from __future__ import annotations

import contextlib
import gc
import json
import os
import stat
import sys
import wave
from pathlib import Path

from meeting_memory.repo.local_model_cache import models, validate_models
from meeting_memory.repo.local_worker_lifetime import worker_parent_lifetime

MAX_REQUEST_BYTES = 4096


class MetalUnavailable(RuntimeError):
    """The process cannot access the required local GPU backend."""


def emit(phase: str, **counts) -> None:
    sys.__stdout__.write(json.dumps({"phase": phase, **counts}) + "\n")
    sys.__stdout__.flush()


def _private_regular(path: Path, *, limit: int | None = None) -> None:
    info = path.lstat()
    parent = path.parent.stat()
    if (
        not path.is_absolute()
        or not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_mode & 0o077
        or info.st_nlink != 1
        or parent.st_uid != os.getuid()
        or parent.st_mode & 0o077
        or (limit is not None and info.st_size > limit)
    ):
        raise ValueError("worker input must be private, regular, and app-owned")


def read_request(path: Path) -> dict:
    _private_regular(path, limit=MAX_REQUEST_BYTES)
    row = json.loads(path.read_text())
    if not isinstance(row, dict) or row.get("operation") not in {"prepare", "infer", "probe"}:
        raise ValueError("invalid operation")
    required = {"operation", "cache"} | ({"audio"} if row["operation"] == "infer" else set())
    if set(row) != required or not isinstance(row["cache"], str):
        raise ValueError("invalid request schema")
    cache = Path(row["cache"])
    if not cache.is_absolute():
        raise ValueError("cache must be absolute")
    if row["operation"] == "infer":
        _private_regular(Path(row["audio"]))
    return row


def download(cache: Path) -> None:
    # This process never receives meeting audio, text, credentials, or implicit HF tokens.
    from huggingface_hub import hf_hub_download
    from tqdm import tqdm

    total = sum(item.size for model in models() for item in model.files)
    completed = 0

    class DownloadProgress(tqdm):
        def update(self, n=1):
            result = super().update(n)
            if result or self.n == self.total:
                current = min(total, completed + max(0, int(self.n)))
                emit("downloading", completed_bytes=current, total_bytes=total)
            return result

    for model in models():
        for item in model.files:
            existing = model.snapshot(cache) / item.name
            force = False
            if existing.exists():
                import hashlib

                digest = hashlib.sha256()
                with existing.open("rb") as source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        digest.update(chunk)
                force = existing.stat().st_size != item.size or digest.hexdigest() != item.sha256
            emit("downloading", completed_bytes=completed, total_bytes=total)
            hf_hub_download(
                repo_id=model.model,
                revision=model.revision,
                filename=item.name,
                cache_dir=str(cache),
                token=False,
                force_download=force,
                tqdm_class=DownloadProgress,
            )
            completed += item.size
    emit("checking")
    validate_models(cache)
    emit("ready")


def _field(value, key: str, default=None):
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


def transcribe(audio: Path, snapshot: Path) -> tuple[list[dict], str]:
    import mlx.core as mx
    from mlx_audio.stt import load

    emit("loading-transcription")
    model = load(snapshot, strict=True, model_type="whisper")
    mx.eval(model.parameters())
    emit("transcribing")
    result = model.generate(
        str(audio),
        language=None,
        task="transcribe",
        word_timestamps=True,
        condition_on_previous_text=False,
        verbose=None,
    )
    mx.synchronize()
    segments = []
    for segment in _field(result, "segments", ()) or ():
        text = str(_field(segment, "text", ""))
        if not text.strip():
            continue
        words = []
        for word in _field(segment, "words", ()) or ():
            text_word = str(_field(word, "word", _field(word, "text", "")))
            if text_word.strip():
                words.append(
                    {
                        "text": text_word,
                        "start": _field(word, "start"),
                        "end": _field(word, "end"),
                    }
                )
        segments.append(
            {
                "start": float(_field(segment, "start")),
                "end": float(_field(segment, "end")),
                "text": text,
                "words": words,
            }
        )
    language = str(_field(result, "language", "") or "")
    del result, model
    gc.collect()
    mx.clear_cache()
    if not segments:
        raise ValueError("no speech recognized")
    return segments, language


def diarize(audio: Path, snapshot: Path) -> list[dict]:
    import mlx.core as mx
    from mlx_audio.vad import load

    emit("loading-diarization")
    model = load(snapshot, strict=True, model_type="nemotron_diarization")
    mx.eval(model.parameters())
    emit("diarizing")
    result = model.generate(str(audio), threshold=0.5)
    mx.synchronize()
    turns = [
        {"start": float(turn.start), "end": float(turn.end), "speaker": str(turn.speaker)}
        for turn in result.segments
    ]
    del result, model
    gc.collect()
    mx.clear_cache()
    if not turns:
        raise ValueError("no diarization returned")
    return turns


def infer(row: dict, destination: Path) -> None:
    # These flags are set before any SDK import even when dispatched from a frozen entrypoint.
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    import socket

    def deny_network(*_args, **_kwargs):
        raise RuntimeError("network unavailable during local inference")

    socket.socket.connect = deny_network
    socket.create_connection = deny_network
    import mlx.core as mx

    if not mx.metal.is_available():
        raise MetalUnavailable()
    mx.set_cache_limit(512 * 1024**2)
    mx.random.seed(0)
    emit("checking")
    whisper, nemotron = validate_models(Path(row["cache"]))
    audio = Path(row["audio"])
    with wave.open(str(audio), "rb") as pcm:
        if pcm.getnchannels() != 1 or pcm.getframerate() != 16000 or pcm.getsampwidth() != 2:
            raise ValueError("unexpected PCM format")
    segments, language = transcribe(audio, whisper)
    turns = diarize(audio, nemotron)
    destination.write_text(
        json.dumps(
            {
                "segments": segments,
                "turns": turns,
                "language": language,
            },
            ensure_ascii=False,
            allow_nan=False,
        )
    )
    destination.chmod(0o600)


def main(argv: list[str] | None = None) -> int:
    os.umask(0o077)
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        return 2
    try:
        request = Path(args[0])
        row = read_request(request)
        # Suppress all SDK output; only allowlisted progress goes through emit().
        with worker_parent_lifetime(request, row), open(os.devnull, "w") as discard:
            with contextlib.redirect_stdout(discard), contextlib.redirect_stderr(discard):
                if row["operation"] == "prepare":
                    download(Path(row["cache"]))
                elif row["operation"] == "probe":
                    import mlx.core as mx
                    from mlx_audio.stt.models.whisper import Model as WhisperModel
                    from mlx_audio.vad.models.nemotron_diarization import Model as DiarizerModel

                    available = mx.metal.is_available() and WhisperModel and DiarizerModel
                    result = {"metal_available": bool(available)}
                    (request.parent / "result.json").write_text(json.dumps(result))
                else:
                    infer(row, request.parent / "result.json")
    except MetalUnavailable:
        return 3
    except Exception:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Pinned declarative model manifests and offline Hugging Face cache validation."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from meeting_memory.types.local_transcription import LocalModelsUnavailable


@dataclass(frozen=True, slots=True)
class ModelFile:
    name: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class LocalModel:
    model: str
    revision: str
    files: tuple[ModelFile, ...]

    def snapshot(self, cache: Path) -> Path:
        return cache / ("models--" + self.model.replace("/", "--")) / "snapshots" / self.revision


def models() -> tuple[LocalModel, ...]:
    manifest = Path(__file__).with_name("local_model_manifest.json")
    return tuple(
        LocalModel(row["model"], row["revision"], tuple(ModelFile(**f) for f in row["files"]))
        for row in json.loads(manifest.read_text())
    )


def cache_root() -> Path:
    if value := os.environ.get("HF_HUB_CACHE"):
        return Path(value).expanduser().absolute()
    base = Path(os.environ.get("HF_HOME", Path.home() / ".cache/huggingface")).expanduser()
    return (base / "hub").absolute()


def model_file(snapshot: Path, item: ModelFile) -> Path:
    """Accept standard snapshot/blob links, never an arbitrary symlink destination."""

    resolved_snapshot = snapshot.resolve(strict=True)
    if resolved_snapshot != snapshot.absolute():
        raise ValueError("snapshot path must not redirect")
    candidate = snapshot / item.name
    resolved = candidate.resolve(strict=True)
    blobs = snapshot.parent.parent / "blobs"
    if resolved != candidate.absolute() and resolved.parent != blobs.resolve(strict=True):
        raise ValueError("model file leaves approved snapshot/blob store")
    if not resolved.is_file() or resolved.stat().st_size != item.size:
        raise ValueError("model file is incomplete")
    return resolved


def validate_models(cache: Path, *, hashes: bool = True) -> tuple[Path, ...]:
    snapshots = []
    try:
        for model in models():
            snapshot = model.snapshot(cache)
            declared = {item.name for item in model.files}
            for path in snapshot.iterdir():
                if path.suffix in {".safetensors", ".py", ".pkl", ".pickle", ".pt", ".pth", ".bin"}:
                    if path.name not in declared:
                        raise ValueError("unexpected executable or weight file")
            for item in model.files:
                candidate = model_file(snapshot, item)
                if hashes:
                    digest = hashlib.sha256()
                    with candidate.open("rb") as source:
                        for chunk in iter(lambda: source.read(1024 * 1024), b""):
                            digest.update(chunk)
                    if digest.hexdigest() != item.sha256:
                        raise ValueError("model file checksum differs")
            snapshots.append(snapshot)
    except (OSError, ValueError):
        raise LocalModelsUnavailable(
            "Local models are missing, incomplete, or could not be verified.",
            "Choose Prepare Local Models, check available disk space, and retry.",
        ) from None
    return tuple(snapshots)

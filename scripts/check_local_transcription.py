#!/usr/bin/env python3
"""Run an explicit Apple Silicon integration check against one private M4A file."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

from meeting_memory.repo.local_transcription import LocalTranscriptionClient
from meeting_memory.types.local_transcription import LocalTranscriptionError


def emit(value: dict) -> None:
    sys.stdout.write(json.dumps(value, sort_keys=True) + "\n")
    sys.stdout.flush()


def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_private_output(path: Path, value: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.parent.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("The output directory must be private to the current user.")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as target:
        json.dump(value, target, ensure_ascii=False, allow_nan=False, indent=2)
        target.write("\n")


def check(args: argparse.Namespace) -> dict:
    source_path = args.audio.expanduser().absolute()
    descriptor = os.open(source_path, os.O_RDONLY | os.O_NOFOLLOW)
    started = time.monotonic()
    with os.fdopen(descriptor, "rb") as source:
        original = os.fstat(source.fileno())
        if not stat.S_ISREG(original.st_mode):
            raise ValueError("The input must be a regular M4A recording.")
        with tempfile.TemporaryDirectory(prefix="meeting-memory-check-") as directory:
            private_audio = Path(directory) / "audio.m4a"
            before = hashlib.sha256()
            with private_audio.open("xb") as snapshot:
                os.chmod(private_audio, 0o600)
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    before.update(chunk)
                    snapshot.write(chunk)
                snapshot.flush()
                os.fsync(snapshot.fileno())
            after_copy = os.fstat(source.fileno())
            if (original.st_dev, original.st_ino, original.st_size, original.st_mtime_ns) != (
                after_copy.st_dev,
                after_copy.st_ino,
                after_copy.st_size,
                after_copy.st_mtime_ns,
            ):
                raise ValueError("The source changed while its private snapshot was copied.")
            with private_audio.open("rb") as snapshot:
                private_audio.unlink()
                result = LocalTranscriptionClient(helper=args.helper).transcribe(
                    snapshot,
                    progress=lambda event: emit({"phase": event.phase}),
                )
        if args.expected_language and result.language != args.expected_language:
            raise ValueError("The detected language did not match the expected language.")
        if digest_file(source_path) != before.hexdigest():
            raise ValueError("The original recording did not retain its content hash.")
        summary = {
            "language": result.language,
            "duration_seconds": result.duration_seconds,
            "segments": len(result.segments),
            "words": sum(len(segment.words) for segment in result.segments),
            "diarization_turns": len(result.turns),
            "speaker_count": len({turn.speaker for turn in result.turns}),
            "elapsed_seconds": time.monotonic() - started,
            "source_unchanged": True,
        }
        if args.output:
            write_private_output(args.output, {"summary": summary, "result": asdict(result)})
        return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path, help="existing M4A recording; never modified")
    parser.add_argument("--expected-language", help="expected detected code, for example en or es")
    parser.add_argument("--helper", type=Path, help="explicit native capture helper for a worktree")
    parser.add_argument(
        "--output",
        type=Path,
        help="optional new result file in a private directory (contains meeting text)",
    )
    args = parser.parse_args(argv)
    try:
        summary = check(args)
    except LocalTranscriptionError as error:
        sys.stderr.write(f"{error} {error.action}\n")
        return 1
    except (OSError, ValueError):
        sys.stderr.write(
            "Local integration validation failed. Check input, expected language, "
            "and private output-directory permissions.\n"
        )
        return 1
    emit(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

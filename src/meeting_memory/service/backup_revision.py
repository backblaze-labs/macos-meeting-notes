"""Deterministic schema-v2 backup revisions and immutable snapshots."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

BACKUP_REVISION_DOMAIN = b"meeting-memory-backup-v2\0"
EXCLUDED_FRONTMATTER_FIELDS = frozenset(
    {"backup_status", "b2_audio", "b2_transcript", "backup_uploaded_revision"}
)
TOP_LEVEL_FIELD = re.compile(r"^([A-Za-z0-9_-]+):(?:[ \t]*(.*))?$")


@dataclass(frozen=True)
class BackupSnapshot:
    """Matching file-backed copies captured for one attempted upload."""

    revision: str
    audio_path: Path
    transcript_path: Path
    normalized_transcript_path: Path
    directory: Path

    def cleanup(self) -> None:
        shutil.rmtree(self.directory)

    def __enter__(self) -> BackupSnapshot:
        return self

    def __exit__(self, *_args: object) -> None:
        self.cleanup()


def normalize_transcript_for_backup(transcript: bytes | str) -> bytes:
    """Remove only Backup bookkeeping fields, normalize LF, end in one LF."""

    raw = transcript.encode("utf-8") if isinstance(transcript, str) else transcript
    text = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    if not lines or lines[0] != "---":
        raise ValueError("transcript is missing top-level YAML frontmatter")

    output = ["---"]
    skipping_field = False
    closed = False
    for line in lines[1:]:
        if line == "---":
            output.append(line)
            closed = True
            break
        match = TOP_LEVEL_FIELD.match(line)
        if match:
            excluded = match.group(1) in EXCLUDED_FRONTMATTER_FIELDS
            raw_value = (match.group(2) or "").strip()
            skipping_field = excluded and raw_value.startswith(("|", ">"))
            if not excluded:
                output.append(line)
            continue
        if skipping_field and (line.startswith((" ", "\t")) or not line):
            continue
        skipping_field = False
        output.append(line)
    if not closed:
        raise ValueError("transcript YAML frontmatter is not closed")

    closing_index = lines[1:].index("---") + 1
    output.extend(lines[closing_index + 1 :])
    return ("\n".join(output).rstrip("\n") + "\n").encode("utf-8")


def backup_revision(audio: bytes, transcript: bytes | str) -> str:
    normalized = normalize_transcript_for_backup(transcript)
    digest = hashlib.sha256()
    digest.update(BACKUP_REVISION_DOMAIN)
    digest.update(len(audio).to_bytes(8, "big", signed=False))
    digest.update(audio)
    digest.update(len(normalized).to_bytes(8, "big", signed=False))
    digest.update(normalized)
    return digest.hexdigest()


def compute_backup_revision(audio_path: Path, transcript_path: Path) -> str:
    with _regular_fd(audio_path) as (audio_fd, audio_size):
        with _regular_fd(transcript_path) as (transcript_fd, _):
            transcript = _read_fd(transcript_fd)
        return _revision_from_fd(audio_fd, audio_size, transcript)


def compute_backup_revision_with_transcript(
    audio_path: Path,
    transcript: bytes | str,
) -> str:
    """Hash one audio file against supplied prospective transcript content."""

    with _regular_fd(audio_path) as (audio_fd, audio_size):
        return _revision_from_fd(audio_fd, audio_size, transcript)


def capture_backup_snapshot(
    audio_path: Path,
    transcript_path: Path,
    snapshot_root: Path | None = None,
) -> BackupSnapshot:
    """Copy a stable upload pair; never use hardlinks to mutable originals."""

    with _regular_fd(audio_path) as (audio_fd, _):
        with _regular_fd(transcript_path) as (transcript_fd, _):
            parent = snapshot_root or (
                transcript_path.parent.parent
                / ".meeting-memory-staging"
                / "backup-snapshots"
            )
            parent.mkdir(parents=True, exist_ok=True)
            directory = Path(tempfile.mkdtemp(prefix="backup.", dir=parent))
            snapshot_audio = directory / "recording.m4a"
            snapshot_transcript = directory / "transcript.md"
            normalized_path = directory / "transcript.normalized.md"
            try:
                _copy_fd(audio_fd, snapshot_audio)
                _copy_fd(transcript_fd, snapshot_transcript)
                normalized_path.write_bytes(
                    normalize_transcript_for_backup(snapshot_transcript.read_bytes())
                )
                revision = compute_backup_revision(snapshot_audio, snapshot_transcript)
            except BaseException:
                shutil.rmtree(directory)
                raise
    return BackupSnapshot(
        revision=revision,
        audio_path=snapshot_audio,
        transcript_path=snapshot_transcript,
        normalized_transcript_path=normalized_path,
        directory=directory,
    )


@contextmanager
def _regular_fd(path: Path) -> Iterator[tuple[int, int]]:
    """Open without following the final symlink and reject non-regular sources."""

    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    descriptor = os.open(path, flags)
    try:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            raise ValueError(f"backup source is not a regular file: {path}")
        yield descriptor, file_stat.st_size
    finally:
        os.close(descriptor)


def _read_fd(descriptor: int) -> bytes:
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while chunk := os.read(descriptor, 1024 * 1024):
        chunks.append(chunk)
    return b"".join(chunks)


def _copy_fd(descriptor: int, destination: Path) -> None:
    os.lseek(descriptor, 0, os.SEEK_SET)
    with destination.open("xb") as writer:
        while chunk := os.read(descriptor, 1024 * 1024):
            writer.write(chunk)
        writer.flush()
        os.fsync(writer.fileno())


def _revision_from_fd(audio_fd: int, audio_size: int, transcript: bytes | str) -> str:
    normalized = normalize_transcript_for_backup(transcript)
    digest = hashlib.sha256()
    digest.update(BACKUP_REVISION_DOMAIN)
    digest.update(audio_size.to_bytes(8, "big", signed=False))
    os.lseek(audio_fd, 0, os.SEEK_SET)
    while chunk := os.read(audio_fd, 1024 * 1024):
        digest.update(chunk)
    digest.update(len(normalized).to_bytes(8, "big", signed=False))
    digest.update(normalized)
    return digest.hexdigest()

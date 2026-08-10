"""Pinned snapshots and compare-and-replace writes for legacy meetings."""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

from meeting_memory.service.atomic_io import atomic_replace_text_at
from meeting_memory.service.frontmatter import split_frontmatter
from meeting_memory.service.ownership import classify_ownership
from meeting_memory.service.pinned_fs import open_directory_tree
from meeting_memory.service.transcription_audio import private_stable_copy
from meeting_memory.types.artifacts import (
    ArtifactOwnership,
    LegacyBackupUpload,
    LegacyUploadObject,
)
from meeting_memory.types.meeting import MeetingMeta, validate_meeting_slug


@dataclass(frozen=True)
class LegacyDocumentSnapshot:
    directory: Path
    directory_device: int
    directory_inode: int
    metadata_name: str
    metadata_device: int
    metadata_inode: int
    metadata_text: str
    frontmatter: dict[str, object]

    @property
    def meta(self) -> MeetingMeta:
        speakers = self.frontmatter.get("speaker_candidates")
        return MeetingMeta(
            validate_meeting_slug(str(self.frontmatter["id"])),
            datetime.fromisoformat(str(self.frontmatter["date"])),
            str(self.frontmatter.get("calendar_title") or "Untitled"),
            int(self.frontmatter.get("duration_minutes") or 0),
            tuple(str(item) for item in speakers) if isinstance(speakers, list) else (),
        )


@dataclass(frozen=True)
class LegacyMeetingSnapshot(LegacyDocumentSnapshot):
    audio: tuple[LegacyUploadObject, ...]
    transcript: LegacyUploadObject

    def backup_request(self) -> LegacyBackupUpload:
        return LegacyBackupUpload(self.meta.slug, self.audio, self.transcript)


@contextmanager
def capture_legacy_snapshot(meeting_dir: Path) -> Iterator[LegacyMeetingSnapshot]:
    """Copy one owned legacy meeting through a single pinned directory fd."""

    candidate = Path(os.path.abspath(meeting_dir.expanduser()))
    root = candidate.parent.resolve(strict=True)
    root_fd = open_directory_tree(root)
    directory_fd = metadata_fd = -1
    streams: list[BinaryIO] = []
    try:
        directory_fd = os.open(
            candidate.name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=root_fd,
        )
        directory_info = os.fstat(directory_fd)
        metadata_name, metadata_fd = _open_metadata(directory_fd)
        metadata_info = os.fstat(metadata_fd)
        transcript_stream = private_stable_copy(metadata_fd)
        streams.append(transcript_stream)
        metadata_text = transcript_stream.read().decode("utf-8")
        transcript_stream.seek(0)
        frontmatter, _ = split_frontmatter(metadata_text)
        if classify_ownership(frontmatter, metadata_name) is not ArtifactOwnership.LEGACY:
            raise ValueError("legacy retry requires an owned legacy artifact")
        transcript = LegacyUploadObject(metadata_name, transcript_stream)
        audio: list[LegacyUploadObject] = []
        for name in _audio_names(directory_fd):
            descriptor = _open_regular_at(directory_fd, name)
            try:
                item = LegacyUploadObject(name, private_stable_copy(descriptor))
            finally:
                os.close(descriptor)
            streams.append(item.stream)
            audio.append(item)
        if not audio:
            raise ValueError("legacy retry requires at least one recording")
        yield LegacyMeetingSnapshot(
            directory=candidate,
            directory_device=directory_info.st_dev,
            directory_inode=directory_info.st_ino,
            metadata_name=metadata_name,
            metadata_device=metadata_info.st_dev,
            metadata_inode=metadata_info.st_ino,
            metadata_text=metadata_text,
            frontmatter=frontmatter,
            audio=tuple(audio),
            transcript=transcript,
        )
    finally:
        for stream in streams:
            stream.close()
        if metadata_fd >= 0:
            os.close(metadata_fd)
        if directory_fd >= 0:
            os.close(directory_fd)
        os.close(root_fd)


@contextmanager
def capture_legacy_document_snapshot(
    meeting_dir: Path,
) -> Iterator[LegacyDocumentSnapshot]:
    """Capture only one legacy metadata file for local derived Notes."""

    candidate = Path(os.path.abspath(meeting_dir.expanduser()))
    root_fd = open_directory_tree(candidate.parent.resolve(strict=True))
    directory_fd = metadata_fd = -1
    transcript_stream: BinaryIO | None = None
    try:
        directory_fd = os.open(
            candidate.name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=root_fd,
        )
        directory_info = os.fstat(directory_fd)
        metadata_name, metadata_fd = _open_metadata(directory_fd)
        metadata_info = os.fstat(metadata_fd)
        transcript_stream = private_stable_copy(metadata_fd)
        metadata_text = transcript_stream.read().decode("utf-8")
        frontmatter, _ = split_frontmatter(metadata_text)
        if classify_ownership(frontmatter, metadata_name) is not ArtifactOwnership.LEGACY:
            raise ValueError("legacy Notes require an owned legacy artifact")
        yield LegacyDocumentSnapshot(
            candidate,
            directory_info.st_dev,
            directory_info.st_ino,
            metadata_name,
            metadata_info.st_dev,
            metadata_info.st_ino,
            metadata_text,
            frontmatter,
        )
    finally:
        if transcript_stream is not None:
            transcript_stream.close()
        if metadata_fd >= 0:
            os.close(metadata_fd)
        if directory_fd >= 0:
            os.close(directory_fd)
        os.close(root_fd)


def replace_legacy_metadata(snapshot: LegacyDocumentSnapshot, text: str) -> None:
    """Replace only the exact unchanged legacy metadata file captured earlier."""

    with _unchanged_legacy_directory(snapshot) as (directory_fd, metadata_fd):
        _validate_unchanged_metadata(snapshot, directory_fd, metadata_fd)
        atomic_replace_text_at(directory_fd, snapshot.metadata_name, text)


def write_legacy_notes(snapshot: LegacyDocumentSnapshot, text: str) -> Path:
    """Publish notes only beside the exact unchanged legacy transcript."""

    with _unchanged_legacy_directory(snapshot) as (directory_fd, metadata_fd):
        try:
            notes = os.stat("notes.md", dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            if not stat.S_ISREG(notes.st_mode):
                raise ValueError("legacy notes.md must be a regular file")
        _validate_unchanged_metadata(snapshot, directory_fd, metadata_fd)
        atomic_replace_text_at(directory_fd, "notes.md", text)
    return snapshot.directory / "notes.md"


@contextmanager
def _unchanged_legacy_directory(
    snapshot: LegacyDocumentSnapshot,
) -> Iterator[tuple[int, int]]:
    root_fd = open_directory_tree(snapshot.directory.parent.resolve(strict=True))
    directory_fd = metadata_fd = -1
    try:
        directory_fd = os.open(
            snapshot.directory.name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=root_fd,
        )
        directory_info = os.fstat(directory_fd)
        metadata_fd = _open_regular_at(directory_fd, snapshot.metadata_name)
        if (
            (directory_info.st_dev, directory_info.st_ino)
            != (snapshot.directory_device, snapshot.directory_inode)
        ):
            raise ValueError("legacy meeting changed before update")
        _validate_unchanged_metadata(snapshot, directory_fd, metadata_fd)
        yield directory_fd, metadata_fd
    finally:
        if metadata_fd >= 0:
            os.close(metadata_fd)
        if directory_fd >= 0:
            os.close(directory_fd)
        os.close(root_fd)


def _validate_unchanged_metadata(
    snapshot: LegacyDocumentSnapshot,
    directory_fd: int,
    metadata_fd: int,
) -> None:
    opened = os.fstat(metadata_fd)
    current = _read_text(metadata_fd)
    visible = os.stat(
        snapshot.metadata_name,
        dir_fd=directory_fd,
        follow_symlinks=False,
    )
    frontmatter, _ = split_frontmatter(current)
    expected = (snapshot.metadata_device, snapshot.metadata_inode)
    if (
        not stat.S_ISREG(visible.st_mode)
        or (opened.st_dev, opened.st_ino) != expected
        or (visible.st_dev, visible.st_ino) != expected
        or current != snapshot.metadata_text
        or classify_ownership(frontmatter, snapshot.metadata_name)
        is not ArtifactOwnership.LEGACY
    ):
        raise ValueError("legacy meeting metadata changed before update")


def _open_metadata(directory_fd: int) -> tuple[str, int]:
    for name in ("transcript.md", "meeting.md"):
        try:
            return name, _open_regular_at(directory_fd, name)
        except FileNotFoundError:
            continue
    raise FileNotFoundError("legacy meeting metadata is missing")


def _audio_names(directory_fd: int) -> tuple[str, ...]:
    names: list[str] = []
    for name in os.listdir(directory_fd):
        if name != "recording.m4a" and not (
            name.startswith("recording") and name.endswith(".m4a")
        ):
            continue
        try:
            info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except OSError:
            continue
        if stat.S_ISREG(info.st_mode):
            names.append(name)
    return tuple(sorted(names, key=lambda value: (value != "recording.m4a", value)))


def _open_regular_at(directory_fd: int, name: str) -> int:
    descriptor = os.open(
        name,
        os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
        dir_fd=directory_fd,
    )
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise ValueError(f"legacy artifact is not regular: {name}")
    return descriptor


def _read_text(descriptor: int) -> str:
    chunks: list[bytes] = []
    for offset in range(0, os.fstat(descriptor).st_size, 1024 * 1024):
        chunks.append(os.pread(descriptor, 1024 * 1024, offset))
    return b"".join(chunks).decode("utf-8")

"""Pinned no-follow access to one owned schema-v2 meeting document."""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from meeting_memory.service.atomic_io import (
    AtomicReplaceDurabilityUncertain,
    atomic_replace_text_at,
)
from meeting_memory.service.frontmatter import split_frontmatter
from meeting_memory.service.pinned_fs import open_directory_tree
from meeting_memory.types.backup import backup_revision_stream
from meeting_memory.types.meeting import MeetingDirectoryIdentity, validate_meeting_slug


@dataclass
class MeetingDocument:
    path: Path
    root_path: Path
    directory_fd: int
    text: str
    frontmatter: dict[str, object]

    def replace_transcript(self, text: str) -> None:
        try:
            atomic_replace_text_at(self.directory_fd, "transcript.md", text)
        except AtomicReplaceDurabilityUncertain as exc:
            self.text = text
            self.frontmatter, _ = split_frontmatter(text)
            raise MeetingDocumentDurabilityUncertain(
                self.path,
                self.frontmatter.copy(),
                exc,
            ) from exc
        self.text = text
        self.frontmatter, _ = split_frontmatter(text)

    def backup_revision(self, transcript: bytes | str | None = None) -> str:
        audio_fd = _open_regular_at(self.directory_fd, "recording.m4a")
        try:
            content = self.text if transcript is None else transcript
            info = os.fstat(audio_fd)
            with os.fdopen(os.dup(audio_fd), "rb") as stream:
                return backup_revision_stream(stream, info.st_size, content)
        finally:
            os.close(audio_fd)


class MeetingDocumentDurabilityUncertain(RuntimeError):
    """A transcript update is visible but its directory flush failed."""

    def __init__(
        self,
        path: Path,
        frontmatter: dict[str, object],
        cause: AtomicReplaceDurabilityUncertain,
    ) -> None:
        self.path = path
        self.frontmatter = frontmatter
        self.cause = cause
        super().__init__(f"transcript update at {path} is visible; durability is uncertain")


@contextmanager
def open_meeting_document(
    meetings_dir: Path,
    meeting_dir: Path,
) -> Iterator[MeetingDocument]:
    """Pin the root and direct-child directory before any artifact access."""

    lexical_root = _absolute_path(meetings_dir)
    candidate = _absolute_path(meeting_dir)
    validate_meeting_slug(candidate.name)
    if candidate.parent != lexical_root:
        raise ValueError("meeting directory must be a direct child of MEETINGS_DIR")
    root = lexical_root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("MEETINGS_DIR must resolve to a directory")

    root_fd = open_directory_tree(root)
    directory_fd = -1
    try:
        directory_fd = os.open(
            candidate.name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=root_fd,
        )
        transcript_fd = _open_regular_at(directory_fd, "transcript.md")
        try:
            text = _read_text_fd(transcript_fd)
        finally:
            os.close(transcript_fd)
        audio_fd = _open_regular_at(directory_fd, "recording.m4a")
        os.close(audio_fd)
        frontmatter, _ = split_frontmatter(text)
        _validate_identity(candidate.name, frontmatter)
        yield MeetingDocument(
            lexical_root / candidate.name,
            root,
            directory_fd,
            text,
            frontmatter,
        )
    finally:
        if directory_fd >= 0:
            os.close(directory_fd)
        os.close(root_fd)


def validate_meeting_document(meetings_dir: Path, meeting_dir: Path) -> None:
    """Perform a read-only pinned validation before any lock file is created."""

    with open_meeting_document(meetings_dir, meeting_dir):
        return


def require_meeting_directory_identity(
    document: MeetingDocument,
    expected: MeetingDirectoryIdentity | None,
) -> None:
    """Reject a path-replacement clone while operating on a pinned document."""

    if expected is None:
        return
    info = os.fstat(document.directory_fd)
    if (info.st_dev, info.st_ino) != (expected.device, expected.inode):
        raise ValueError("meeting directory identity changed")


def _open_regular_at(directory_fd: int, filename: str) -> int:
    descriptor = os.open(
        filename,
        os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
        dir_fd=directory_fd,
    )
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise ValueError(f"meeting artifact is not a regular file: {filename}")
    return descriptor


def _read_text_fd(descriptor: int) -> str:
    chunks: list[bytes] = []
    while chunk := os.read(descriptor, 1024 * 1024):
        chunks.append(chunk)
    return b"".join(chunks).decode("utf-8")


def _validate_identity(name: str, frontmatter: dict[str, object]) -> None:
    if (
        frontmatter.get("created_by") != "meeting-memory"
        or frontmatter.get("schema_version") != 2
    ):
        raise ValueError("state writes require an owned schema-v2 transcript")
    if frontmatter.get("id") != name:
        raise ValueError("meeting frontmatter id must match its directory name")


def _absolute_path(path: Path) -> Path:
    return Path(os.path.abspath(path.expanduser()))

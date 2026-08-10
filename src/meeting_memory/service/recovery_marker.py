"""Opaque in-directory marker that makes recovery publication discoverable."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

from meeting_memory.service.atomic_io import atomic_replace_text_at
from meeting_memory.service.frontmatter import split_frontmatter
from meeting_memory.service.markdown import safe_frontmatter_text
from meeting_memory.service.pinned_fs import open_directory_tree, read_regular_text_at
from meeting_memory.types.meeting import MeetingMeta, PostCommitPolicy, validate_meeting_slug
from meeting_memory.types.recovery import RecoveryIndexEntry, RecoveryPublication

MARKER_FILENAME = ".meeting-memory-recovery.json"
MARKER_VERSION = 1


def write_recovery_marker(stage: Path, final_meta: MeetingMeta, token: str) -> None:
    validate_meeting_slug(final_meta.slug)
    directory_fd = os.open(stage, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        directory = os.fstat(directory_fd)
        audio_fd = os.open(
            "recording.m4a",
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=directory_fd,
        )
        try:
            audio = os.fstat(audio_fd)
            if not stat.S_ISREG(audio.st_mode) or audio.st_size <= 0:
                raise ValueError("recovery marker requires regular audio")
            digest = _sha256(audio_fd, audio.st_size)
        finally:
            os.close(audio_fd)
        atomic_replace_text_at(
            directory_fd,
            MARKER_FILENAME,
            json.dumps(
                {
                    "version": MARKER_VERSION,
                    "token": token,
                    "directory_device": directory.st_dev,
                    "directory_inode": directory.st_ino,
                    "audio_device": audio.st_dev,
                    "audio_inode": audio.st_ino,
                    "audio_size": audio.st_size,
                    "audio_sha256": digest,
                },
                sort_keys=True,
            ),
        )
    finally:
        os.close(directory_fd)


def find_recovery_publication(
    meetings_dir: Path,
    entry: RecoveryIndexEntry,
    token: str,
    policy: PostCommitPolicy,
) -> RecoveryPublication | None:
    root_fd = open_directory_tree(meetings_dir.expanduser().resolve(strict=True))
    matches: list[RecoveryPublication] = []
    try:
        for name in os.listdir(root_fd):
            if name.startswith("."):
                continue
            publication = _publication_in_child(root_fd, name, entry, token, policy)
            if publication is not None:
                matches.append(publication)
    finally:
        os.close(root_fd)
    if len(matches) > 1:
        raise ValueError("recovery journal token appears in multiple meetings")
    return matches[0] if matches else None


def remove_recovery_marker(
    meetings_dir: Path,
    entry: RecoveryIndexEntry,
    token: str,
) -> None:
    publication = entry.publication
    if publication is None:
        return
    root_fd = open_directory_tree(meetings_dir.expanduser().resolve(strict=True))
    child_fd = -1
    try:
        child_fd = os.open(
            publication.slug,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=root_fd,
        )
        info = os.fstat(child_fd)
        if (info.st_dev, info.st_ino) != (
            publication.directory_device,
            publication.directory_inode,
        ):
            raise ValueError("published meeting changed before marker cleanup")
        marker = json.loads(read_regular_text_at(child_fd, MARKER_FILENAME))
        if not _marker_matches(marker, token):
            raise ValueError("recovery marker changed before cleanup")
        os.unlink(MARKER_FILENAME, dir_fd=child_fd)
        os.fsync(child_fd)
    finally:
        if child_fd >= 0:
            os.close(child_fd)
        os.close(root_fd)


def require_recovery_marker_directory(directory_fd: int, token: str) -> None:
    """Authenticate a token-bound directory without trusting its changed audio."""

    marker = json.loads(read_regular_text_at(directory_fd, MARKER_FILENAME))
    if not _marker_matches(marker, token):
        raise ValueError("recovery publication marker is not authentic")
    directory = os.fstat(directory_fd)
    if (
        marker.get("directory_device") != directory.st_dev
        or marker.get("directory_inode") != directory.st_ino
    ):
        raise ValueError("recovery publication directory identity changed")


def _publication_in_child(
    root_fd: int,
    name: str,
    entry: RecoveryIndexEntry,
    token: str,
    policy: PostCommitPolicy,
) -> RecoveryPublication | None:
    try:
        child_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
    except OSError:
        return None
    try:
        try:
            marker = json.loads(read_regular_text_at(child_fd, MARKER_FILENAME))
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            return None
        if not _marker_matches(marker, token):
            return None
        frontmatter, _ = split_frontmatter(read_regular_text_at(child_fd, "transcript.md"))
        _validate_meta(frontmatter, entry.meta, name)
        audio_fd = os.open(
            "recording.m4a",
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=child_fd,
        )
        try:
            audio = os.fstat(audio_fd)
            if not stat.S_ISREG(audio.st_mode) or audio.st_size <= 0:
                raise ValueError("recovery publication audio is invalid")
            digest = _sha256(audio_fd, audio.st_size)
            if (
                marker.get("audio_size") != audio.st_size
                or marker.get("audio_sha256") != digest
            ):
                raise ValueError("recovery publication audio changed after validation")
        finally:
            os.close(audio_fd)
        directory = os.fstat(child_fd)
        if (
            marker.get("directory_device") != directory.st_dev
            or marker.get("directory_inode") != directory.st_ino
            or marker.get("audio_device") != audio.st_dev
            or marker.get("audio_inode") != audio.st_ino
        ):
            raise ValueError("recovery publication identity changed after validation")
        return RecoveryPublication(
            name,
            directory.st_dev,
            directory.st_ino,
            audio.st_dev,
            audio.st_ino,
            audio.st_size,
            digest,
            entry.source_device,  # type: ignore[arg-type]
            entry.source_inode,  # type: ignore[arg-type]
            entry.source_size,  # type: ignore[arg-type]
            entry.source_sha256,  # type: ignore[arg-type]
            policy,
        )
    finally:
        os.close(child_fd)


def _validate_meta(frontmatter: dict[str, object], meta: MeetingMeta, slug: str) -> None:
    expected = {
        "created_by": "meeting-memory",
        "schema_version": 2,
        "id": slug,
        "date": meta.started_at.isoformat(),
        "duration_minutes": meta.duration_minutes,
        "calendar_title": safe_frontmatter_text(meta.calendar_title),
    }
    if any(frontmatter.get(key) != value for key, value in expected.items()):
        raise ValueError("recovery publication metadata changed")


def _marker_matches(marker: object, token: str) -> bool:
    return (
        isinstance(marker, dict)
        and marker.get("version") == MARKER_VERSION
        and marker.get("token") == token
        and isinstance(marker.get("directory_device"), int)
        and isinstance(marker.get("directory_inode"), int)
        and isinstance(marker.get("audio_device"), int)
        and isinstance(marker.get("audio_inode"), int)
        and isinstance(marker.get("audio_size"), int)
        and int(marker["audio_size"]) > 0
        and isinstance(marker.get("audio_sha256"), str)
        and len(str(marker["audio_sha256"])) == 64
    )


def _sha256(descriptor: int, size: int) -> str:
    digest = hashlib.sha256()
    for offset in range(0, size, 1024 * 1024):
        digest.update(os.pread(descriptor, min(1024 * 1024, size - offset), offset))
    return digest.hexdigest()

"""Persistent reconciliation for a visible recovery publication with uncertain fsync."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

from meeting_memory.service.markdown import safe_frontmatter_text
from meeting_memory.service.meeting_document import open_meeting_document
from meeting_memory.service.pinned_fs import open_directory_tree
from meeting_memory.service.recovery_commit import (
    RecoveryCommitResult,
    RecoveryPublicationIdentity,
    issue_recovery_result,
)
from meeting_memory.types.meeting import (
    MeetingDirectoryIdentity,
    MeetingFiles,
    MeetingMeta,
)
from meeting_memory.types.recovery import RecoveryIndexEntry, RecoveryPublication


def reconcile_uncertain_publication(
    meetings_dir: Path,
    entry: RecoveryIndexEntry,
) -> RecoveryCommitResult:
    """Re-fsync and receipt the exact recorded publication without republishing."""

    publication = entry.publication
    if publication is None:
        raise ValueError("recovery entry has no uncertain publication")
    meeting_dir = meetings_dir / publication.slug
    meta = entry.meta.with_slug(publication.slug)
    with open_meeting_document(meetings_dir, meeting_dir) as document:
        info = os.fstat(document.directory_fd)
        if (info.st_dev, info.st_ino) != (
            publication.directory_device,
            publication.directory_inode,
        ):
            raise ValueError("uncertain publication directory changed")
        _validate_meta(document.frontmatter, meta)
        _validate_audio(document.directory_fd, publication)
        os.fsync(document.directory_fd)
    root_fd = open_directory_tree(meetings_dir.expanduser().resolve(strict=True))
    try:
        os.fsync(root_fd)
    finally:
        os.close(root_fd)
    files = MeetingFiles(
        meta,
        meeting_dir,
        meeting_dir / "recording.m4a",
        meeting_dir / "transcript.md",
        meeting_dir / "notes.md",
        directory_identity=MeetingDirectoryIdentity(
            publication.directory_device,
            publication.directory_inode,
        ),
    )
    identity = RecoveryPublicationIdentity(
        publication.directory_device,
        publication.directory_inode,
        publication.audio_device,
        publication.audio_inode,
        publication.audio_size,
        publication.audio_sha256,
    )
    return issue_recovery_result(entry, files, identity, cleanup_allowed=True)


def _validate_meta(frontmatter: dict[str, object], meta: MeetingMeta) -> None:
    expected = {
        "id": meta.slug,
        "date": meta.started_at.isoformat(),
        "duration_minutes": meta.duration_minutes,
        "calendar_title": safe_frontmatter_text(meta.calendar_title),
    }
    if any(frontmatter.get(key) != value for key, value in expected.items()):
        raise ValueError("uncertain publication metadata changed")


def _validate_audio(directory_fd: int, publication: RecoveryPublication) -> None:
    audio_fd = os.open(
        "recording.m4a",
        os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
        dir_fd=directory_fd,
    )
    try:
        opened = os.fstat(audio_fd)
        visible = os.stat("recording.m4a", dir_fd=directory_fd, follow_symlinks=False)
        identity = (publication.audio_device, publication.audio_inode)
        if (
            not stat.S_ISREG(opened.st_mode)
            or identity != (opened.st_dev, opened.st_ino)
            or identity != (visible.st_dev, visible.st_ino)
            or opened.st_size != publication.audio_size
            or _sha256(audio_fd, opened.st_size) != publication.audio_sha256
        ):
            raise ValueError("uncertain publication audio changed")
    finally:
        os.close(audio_fd)


def _sha256(descriptor: int, size: int) -> str:
    digest = hashlib.sha256()
    for offset in range(0, size, 1024 * 1024):
        digest.update(os.pread(descriptor, min(1024 * 1024, size - offset), offset))
    return digest.hexdigest()

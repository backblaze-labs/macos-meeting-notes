"""Post-commit no-follow cleanup for indexed and legacy recovery sources."""

from __future__ import annotations

import hashlib
import os
import stat

from meeting_memory.service.meeting_document import open_meeting_document
from meeting_memory.service.pinned_fs import open_directory_tree
from meeting_memory.service.recovery_commit import RecoveryCleanupReceipt
from meeting_memory.service.recovery_index import INDEX_FILENAME
from meeting_memory.types.recovery import (
    RecoveryIndexEntry,
    RecoveryOrigin,
)


def cleanup_recovery_after_commit(receipt: RecoveryCleanupReceipt) -> None:
    """Remove only the source bound to the still-published committed directory."""

    if not isinstance(receipt, RecoveryCleanupReceipt):
        raise TypeError("recovery cleanup requires a commit-issued receipt")
    receipt.require_issued()
    if not receipt.cleanup_allowed:
        raise ValueError("recovery cleanup is prohibited while durability is uncertain")
    with open_meeting_document(
        receipt.committed_directory.parent,
        receipt.committed_directory,
    ) as document:
        _require_identity(
            document.directory_fd,
            receipt.committed_device,
            receipt.committed_inode,
            "committed directory",
        )
        if document.path.name != receipt.committed_slug:
            raise ValueError("recovery committed slug changed before cleanup")
        _require_final_audio(document.directory_fd, receipt)
        entry = receipt.entry
        if entry.source_device is None or entry.source_inode is None:
            raise ValueError("recovery receipt lost its pinned source identity")
        _cleanup_entry(entry)


def _require_final_audio(
    directory_fd: int,
    receipt: RecoveryCleanupReceipt,
) -> None:
    descriptor = os.open(
        "recording.m4a",
        os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
        dir_fd=directory_fd,
    )
    try:
        opened = os.fstat(descriptor)
        visible = os.stat(
            "recording.m4a", dir_fd=directory_fd, follow_symlinks=False
        )
        expected_identity = (receipt.audio_device, receipt.audio_inode)
        if (
            not stat.S_ISREG(opened.st_mode)
            or expected_identity != (opened.st_dev, opened.st_ino)
            or expected_identity != (visible.st_dev, visible.st_ino)
            or opened.st_size != receipt.audio_size
            or _source_sha256(descriptor, opened.st_size) != receipt.audio_sha256
        ):
            raise ValueError("recovery committed audio changed before cleanup")
    finally:
        os.close(descriptor)


def _cleanup_entry(entry: RecoveryIndexEntry) -> None:
    if entry.origin is RecoveryOrigin.APP_STAGING:
        _cleanup_indexed_source(entry)
    else:
        _cleanup_legacy_source(entry)


def _cleanup_indexed_source(entry: RecoveryIndexEntry) -> None:
    session = entry.session_directory
    if entry.source_path.parent != session or entry.index_path != session / INDEX_FILENAME:
        raise ValueError("indexed recovery paths escaped their private session")
    parent_fd = open_directory_tree(session.parent)
    session_fd = -1
    try:
        try:
            session_fd = os.open(
                session.name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=parent_fd,
            )
        except FileNotFoundError:
            return
        _require_identity(session_fd, entry.session_device, entry.session_inode, "session")
        _unlink_same_regular(
            session_fd,
            entry.source_path.name,
            entry.source_device,
            entry.source_inode,
            entry.source_size,
            entry.source_sha256,
        )
        _unlink_regular(session_fd, INDEX_FILENAME)
        os.fsync(session_fd)
        os.rmdir(session.name, dir_fd=parent_fd)
        os.fsync(parent_fd)
    finally:
        if session_fd >= 0:
            os.close(session_fd)
        os.close(parent_fd)


def _cleanup_legacy_source(entry: RecoveryIndexEntry) -> None:
    if entry.source_path.parent != entry.session_directory:
        raise ValueError("legacy recovery source escaped its scanned directory")
    parent_fd = open_directory_tree(entry.session_directory)
    try:
        _require_identity(parent_fd, entry.session_device, entry.session_inode, "legacy root")
        _unlink_same_regular(
            parent_fd,
            entry.source_path.name,
            entry.source_device,
            entry.source_inode,
            entry.source_size,
            entry.source_sha256,
        )
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)


def _unlink_same_regular(
    directory_fd: int,
    filename: str,
    expected_device: int,
    expected_inode: int,
    expected_size: int | None,
    expected_sha256: str | None,
) -> None:
    try:
        descriptor = os.open(
            filename,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=directory_fd,
        )
    except FileNotFoundError:
        return
    try:
        opened = os.fstat(descriptor)
        current = os.stat(filename, dir_fd=directory_fd, follow_symlinks=False)
        identity = (expected_device, expected_inode)
        bytes_match = (
            expected_size is not None
            and expected_sha256 is not None
            and opened.st_size == expected_size
            and _source_sha256(descriptor, opened.st_size) == expected_sha256
        )
        if (
            not stat.S_ISREG(opened.st_mode)
            or identity != (opened.st_dev, opened.st_ino)
            or identity != (current.st_dev, current.st_ino)
            or not bytes_match
        ):
            raise ValueError("recovery source changed before cleanup")
        os.unlink(filename, dir_fd=directory_fd)
    finally:
        os.close(descriptor)


def _unlink_regular(directory_fd: int, filename: str) -> None:
    info = os.stat(filename, dir_fd=directory_fd, follow_symlinks=False)
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("recovery index changed before cleanup")
    os.unlink(filename, dir_fd=directory_fd)


def _require_identity(
    descriptor: int,
    expected_device: int,
    expected_inode: int,
    label: str,
) -> None:
    info = os.fstat(descriptor)
    if (info.st_dev, info.st_ino) != (expected_device, expected_inode):
        raise ValueError(f"recovery {label} was replaced before cleanup")


def _source_sha256(descriptor: int, size: int) -> str:
    digest = hashlib.sha256()
    offset = 0
    while offset < size:
        chunk = os.pread(descriptor, min(1024 * 1024, size - offset), offset)
        if not chunk:
            break
        digest.update(chunk)
        offset += len(chunk)
    return digest.hexdigest()

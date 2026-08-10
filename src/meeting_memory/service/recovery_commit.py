"""Single operation for publishing one pinned recovery source and its receipt."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from meeting_memory.service.meeting_store import CommitDurabilityUncertain, MeetingStore
from meeting_memory.service.pinned_fs import open_directory_tree
from meeting_memory.service.recovery_audio import (
    RecoveryAudioConverter,
    RecoveryM4AValidator,
    recovery_audio_plan,
)
from meeting_memory.types.meeting import MeetingFiles, PostCommitPolicy
from meeting_memory.types.recovery import RecoveryIndexEntry

_RECEIPT_SEAL = object()


@dataclass(frozen=True, slots=True, init=False)
class RecoveryCleanupReceipt:
    """Sealed capability issued only for a published recovery commit."""

    entry: RecoveryIndexEntry
    committed_directory: Path
    committed_slug: str
    committed_device: int
    committed_inode: int
    audio_device: int
    audio_inode: int
    audio_size: int
    audio_sha256: str
    cleanup_allowed: bool
    __seal: object

    def __init__(
        self,
        seal: object,
        entry: RecoveryIndexEntry,
        files: MeetingFiles,
        identity: _PublicationIdentity,
        cleanup_allowed: bool,
    ) -> None:
        if seal is not _RECEIPT_SEAL:
            raise TypeError("recovery cleanup receipts can only be issued by commit_recovery")
        values = {
            "entry": entry,
            "committed_directory": files.directory,
            "committed_slug": files.meta.slug,
            "committed_device": identity.directory_device,
            "committed_inode": identity.directory_inode,
            "audio_device": identity.audio_device,
            "audio_inode": identity.audio_inode,
            "audio_size": identity.audio_size,
            "audio_sha256": identity.audio_sha256,
            "cleanup_allowed": cleanup_allowed,
            "_RecoveryCleanupReceipt__seal": seal,
        }
        for name, value in values.items():
            object.__setattr__(self, name, value)

    def require_issued(self) -> None:
        if self.__seal is not _RECEIPT_SEAL:
            raise TypeError("recovery cleanup receipt is not authentic")


@dataclass(frozen=True)
class RecoveryCommitResult:
    files: MeetingFiles
    receipt: RecoveryCleanupReceipt


@dataclass(frozen=True)
class _PublicationIdentity:
    directory_device: int
    directory_inode: int
    audio_device: int
    audio_inode: int
    audio_size: int
    audio_sha256: str


class RecoveryCommitDurabilityUncertain(RuntimeError):
    """Recovery was published and receipted, but parent durability is uncertain."""

    def __init__(
        self,
        result: RecoveryCommitResult,
        cause: CommitDurabilityUncertain,
    ) -> None:
        self.result = result
        self.cause = cause
        self.durability_uncertain = True
        self.cleanup_error: OSError | None = None
        super().__init__(str(cause))


class RecoveryCommitCleanupUncertain(RuntimeError):
    """Recovery is published and receipted, but closing its source failed."""

    def __init__(self, result: RecoveryCommitResult, cause: OSError) -> None:
        self.result = result
        self.cause = cause
        super().__init__(
            f"recovery committed at {result.files.directory}; source cleanup failed"
        )


def commit_recovery(
    store: MeetingStore,
    entry: RecoveryIndexEntry,
    policy: PostCommitPolicy = PostCommitPolicy(),
    *,
    validate_m4a: RecoveryM4AValidator,
    converter: RecoveryAudioConverter | None = None,
) -> RecoveryCommitResult:
    """Publish bytes from the exact pinned source and issue the only cleanup receipt."""

    source_fd = _open_exact_source(entry)
    published: RecoveryCommitResult | None = None
    durability_outcome: RecoveryCommitDurabilityUncertain | None = None
    try:
        materializer, validate_output = recovery_audio_plan(
            entry, source_fd, converter, validate_m4a
        )
        publication: list[_PublicationIdentity] = []

        def validate_and_capture(path: Path) -> None:
            validate_output(path)
            identity = _capture_publication_identity(path)
            if entry.source_path.suffix.casefold() == ".m4a" and (
                identity.audio_size != entry.source_size
                or identity.audio_sha256 != entry.source_sha256
            ):
                raise ValueError(
                    "materialized M4A does not match the pinned recovery source"
                )
            publication.append(identity)

        try:
            files = store.commit_pinned_audio(
                source_fd,
                entry.meta,
                policy,
                materializer=materializer,
                validate_source=lambda descriptor: _validate_exact_source(
                    entry, descriptor
                ),
                validate_materialized=validate_and_capture,
            )
        except CommitDurabilityUncertain as exc:
            result = _issued_result(
                entry,
                exc.files,
                publication[0],
                cleanup_allowed=False,
            )
            published = result
            durability_outcome = RecoveryCommitDurabilityUncertain(result, exc)
            raise durability_outcome from exc
        published = _issued_result(
            entry,
            files,
            publication[0],
            cleanup_allowed=True,
        )
        return published
    finally:
        try:
            _close_source(source_fd)
        except OSError as exc:
            if durability_outcome is not None:
                durability_outcome.cleanup_error = exc
            elif published is not None:
                raise RecoveryCommitCleanupUncertain(published, exc) from exc
            else:
                raise


def _issued_result(
    entry: RecoveryIndexEntry,
    files: MeetingFiles,
    identity: _PublicationIdentity,
    *,
    cleanup_allowed: bool,
) -> RecoveryCommitResult:
    return RecoveryCommitResult(
        files,
        RecoveryCleanupReceipt(
            _RECEIPT_SEAL,
            entry,
            files,
            identity,
            cleanup_allowed,
        ),
    )


def _capture_publication_identity(audio_path: Path) -> _PublicationIdentity:
    directory_fd = os.open(
        audio_path.parent,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
    )
    audio_fd = -1
    try:
        audio_fd = os.open(
            audio_path.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=directory_fd,
        )
        audio_info = os.fstat(audio_fd)
        visible = os.stat(audio_path.name, dir_fd=directory_fd, follow_symlinks=False)
        if not stat.S_ISREG(audio_info.st_mode) or (
            audio_info.st_dev,
            audio_info.st_ino,
        ) != (visible.st_dev, visible.st_ino):
            raise ValueError("recovery materialized audio changed before publication")
        directory_info = os.fstat(directory_fd)
        return _PublicationIdentity(
            directory_info.st_dev,
            directory_info.st_ino,
            audio_info.st_dev,
            audio_info.st_ino,
            audio_info.st_size,
            _source_sha256(audio_fd, audio_info.st_size),
        )
    finally:
        if audio_fd >= 0:
            os.close(audio_fd)
        os.close(directory_fd)


def _open_exact_source(entry: RecoveryIndexEntry) -> int:
    if entry.source_device is None or entry.source_inode is None:
        raise ValueError("recovery source identity must be pinned before commit")
    if entry.source_size is None or entry.source_sha256 is None:
        raise ValueError("recovery source bytes must be pinned before commit")
    if entry.source_path.parent != entry.session_directory:
        raise ValueError("recovery source escaped its pinned directory")
    directory_fd = open_directory_tree(entry.session_directory)
    try:
        directory_info = os.fstat(directory_fd)
        if (directory_info.st_dev, directory_info.st_ino) != (
            entry.session_device,
            entry.session_inode,
        ):
            raise ValueError("recovery session changed before commit")
        source_fd = os.open(
            entry.source_path.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=directory_fd,
        )
    finally:
        os.close(directory_fd)
    try:
        _validate_exact_source(entry, source_fd)
    except BaseException:
        os.close(source_fd)
        raise
    return source_fd


def _validate_exact_source(entry: RecoveryIndexEntry, source_fd: int) -> None:
    info = os.fstat(source_fd)
    expected = (entry.source_device, entry.source_inode)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_size == 0
        or (info.st_dev, info.st_ino) != expected
        or info.st_size != entry.source_size
        or _source_sha256(source_fd, info.st_size) != entry.source_sha256
    ):
        raise ValueError("recovery source changed before commit")


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


def _close_source(descriptor: int) -> None:
    os.close(descriptor)

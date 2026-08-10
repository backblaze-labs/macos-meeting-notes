"""Single operation for publishing one pinned recovery source and its receipt."""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Callable
from pathlib import Path

from meeting_memory.service.meeting_store import (
    CommitDurabilityUncertain,
    MeetingPublicationIntegrityError,
    MeetingStore,
)
from meeting_memory.service.pinned_fs import open_directory_tree
from meeting_memory.service.recovery_audio import (
    RecoveryAudioConverter,
    RecoveryM4AValidator,
    recovery_audio_plan,
)
from meeting_memory.service.recovery_outcomes import (
    RecoveryCleanupReceipt,
    RecoveryCommitCleanupUncertain,
    RecoveryCommitDurabilityUncertain,
    RecoveryCommitResult,
    RecoveryPublicationIdentity,
    RecoveryPublicationRejected,
    issue_recovery_result,
)
from meeting_memory.service.stage_integrity import PublishedStageIdentity
from meeting_memory.types.meeting import MeetingFiles, MeetingMeta, PostCommitPolicy
from meeting_memory.types.recovery import RecoveryIndexEntry

__all__ = [
    "RecoveryCleanupReceipt",
    "RecoveryCommitCleanupUncertain",
    "RecoveryCommitDurabilityUncertain",
    "RecoveryCommitResult",
    "RecoveryPublicationIdentity",
    "RecoveryPublicationRejected",
    "commit_recovery",
    "issue_recovery_result",
]


def commit_recovery(
    store: MeetingStore,
    entry: RecoveryIndexEntry,
    policy: PostCommitPolicy = PostCommitPolicy(),
    *,
    validate_m4a: RecoveryM4AValidator,
    converter: RecoveryAudioConverter | None = None,
    prepare_publication: Callable[[Path, MeetingMeta], None] | None = None,
    reject_publication: Callable[[Path], None] | None = None,
) -> RecoveryCommitResult:
    """Publish bytes from the exact pinned source and issue the only cleanup receipt."""

    source_fd = _open_exact_source(entry)
    published: RecoveryCommitResult | None = None
    durability_outcome: RecoveryCommitDurabilityUncertain | None = None
    try:
        materializer, validate_output = recovery_audio_plan(
            entry, source_fd, converter, validate_m4a
        )
        publication: list[RecoveryPublicationIdentity] = []

        def validate_snapshot(path: Path) -> None:
            validate_output(path)
            if entry.source_path.suffix.casefold() == ".m4a":
                _validate_snapshot_matches_source(path, entry)

        def observe_publication(
            _files: MeetingFiles,
            identity: PublishedStageIdentity,
        ) -> None:
            publication.append(
                RecoveryPublicationIdentity(
                    identity.directory_device,
                    identity.directory_inode,
                    identity.audio.device,
                    identity.audio.inode,
                    identity.audio.size,
                    identity.audio.sha256,
                )
            )

        try:
            files = store.commit_pinned_audio(
                source_fd,
                entry.meta,
                policy,
                materializer=materializer,
                validate_source=lambda descriptor: _validate_exact_source(
                    entry, descriptor
                ),
                validate_materialized=validate_snapshot,
                prepare_publication=prepare_publication,
                observe_publication=observe_publication,
            )
        except MeetingPublicationIntegrityError as exc:
            quarantine_error: BaseException | None = None
            if reject_publication is not None:
                try:
                    reject_publication(exc.destination)
                except BaseException as quarantine_exc:
                    quarantine_error = quarantine_exc
            raise RecoveryPublicationRejected(
                exc.destination,
                exc.cause,
                quarantine_error,
            ) from exc
        except CommitDurabilityUncertain as exc:
            result = issue_recovery_result(
                entry,
                exc.files,
                publication[0],
                cleanup_allowed=False,
            )
            published = result
            durability_outcome = RecoveryCommitDurabilityUncertain(result, exc)
            raise durability_outcome from exc
        published = issue_recovery_result(
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


def _validate_snapshot_matches_source(
    snapshot_path: Path,
    entry: RecoveryIndexEntry,
) -> None:
    descriptor = os.open(
        snapshot_path,
        os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
    )
    try:
        info = os.fstat(descriptor)
        if (
            info.st_size != entry.source_size
            or _source_sha256(descriptor, info.st_size) != entry.source_sha256
        ):
            raise ValueError("materialized M4A does not match the pinned recovery source")
    finally:
        os.close(descriptor)


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

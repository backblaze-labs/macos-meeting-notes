"""Sealed recovery receipts and typed publication outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from meeting_memory.service.meeting_store import CommitDurabilityUncertain
from meeting_memory.types.meeting import MeetingFiles
from meeting_memory.types.recovery import RecoveryIndexEntry

_RECEIPT_SEAL = object()


@dataclass(frozen=True)
class RecoveryPublicationIdentity:
    directory_device: int
    directory_inode: int
    audio_device: int
    audio_inode: int
    audio_size: int
    audio_sha256: str


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
        identity: RecoveryPublicationIdentity,
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


class RecoveryCommitDurabilityUncertain(RuntimeError):
    def __init__(self, result: RecoveryCommitResult, cause: CommitDurabilityUncertain) -> None:
        self.result = result
        self.cause = cause
        self.durability_uncertain = True
        self.cleanup_error: OSError | None = None
        super().__init__(str(cause))


class RecoveryCommitCleanupUncertain(RuntimeError):
    def __init__(self, result: RecoveryCommitResult, cause: OSError) -> None:
        self.result = result
        self.cause = cause
        super().__init__(
            f"recovery committed at {result.files.directory}; source cleanup failed"
        )


class RecoveryPublicationRejected(RuntimeError):
    def __init__(
        self,
        destination: Path,
        cause: BaseException,
        quarantine_error: BaseException | None,
    ) -> None:
        self.destination = destination
        self.cause = cause
        self.quarantine_error = quarantine_error
        super().__init__("recovery publication failed exact identity validation")


def issue_recovery_result(
    entry: RecoveryIndexEntry,
    files: MeetingFiles,
    identity: RecoveryPublicationIdentity,
    *,
    cleanup_allowed: bool,
) -> RecoveryCommitResult:
    receipt = RecoveryCleanupReceipt(
        _RECEIPT_SEAL,
        entry,
        files,
        identity,
        cleanup_allowed,
    )
    return RecoveryCommitResult(files, receipt)

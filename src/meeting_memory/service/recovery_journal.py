"""Private pre-publication journal for idempotent recovery commits."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from dataclasses import dataclass, replace
from pathlib import Path

from meeting_memory.service.atomic_io import atomic_replace_text_at
from meeting_memory.service.pinned_fs import open_directory_tree, read_regular_text_at
from meeting_memory.service.recovery_marker import (
    find_recovery_publication,
    remove_recovery_marker,
)
from meeting_memory.types.meeting import PostCommitPolicy
from meeting_memory.types.recovery import RecoveryIndexEntry

JOURNAL_DIRECTORY = "recovery-journal"
JOURNAL_VERSION = 1
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class RecoveryBinding:
    entry: RecoveryIndexEntry
    token: str
    policy: PostCommitPolicy


def prepare_recovery_binding(
    meetings_dir: Path,
    entry: RecoveryIndexEntry,
    policy: PostCommitPolicy,
) -> RecoveryBinding:
    """Durably reserve a source token before any final directory can appear."""

    existing = load_recovery_binding(meetings_dir, entry)
    if existing is not None:
        if existing.policy != policy:
            raise ValueError("recovery policy changed after publication was prepared")
        return existing
    _require_provenance(entry)
    token = uuid.uuid4().hex
    root_fd = _open_journal(meetings_dir, create=True)
    try:
        payload = _record_payload(entry, token, policy)
        atomic_replace_text_at(root_fd, _record_name(entry), json.dumps(payload, sort_keys=True))
    finally:
        os.close(root_fd)
    return RecoveryBinding(entry, token, policy)


def load_recovery_binding(
    meetings_dir: Path,
    entry: RecoveryIndexEntry,
) -> RecoveryBinding | None:
    """Load original provenance and discover its atomically published marker."""

    try:
        root_fd = _open_journal(meetings_dir)
    except FileNotFoundError:
        return None
    try:
        try:
            payload = json.loads(read_regular_text_at(root_fd, _record_name(entry)))
        except FileNotFoundError:
            return None
    finally:
        os.close(root_fd)
    pinned, token, policy = _binding_from_payload(payload, entry)
    publication = find_recovery_publication(meetings_dir, pinned, token, policy)
    return RecoveryBinding(replace(pinned, publication=publication), token, policy)


def clear_recovery_binding(meetings_dir: Path, binding: RecoveryBinding) -> None:
    """Clear the durable guard, then best-effort remove its now-harmless marker."""

    root_fd = _open_journal(meetings_dir)
    try:
        name = _record_name(binding.entry)
        payload = json.loads(read_regular_text_at(root_fd, name))
        _, token, policy = _binding_from_payload(payload, binding.entry)
        if token != binding.token or policy != binding.policy:
            raise ValueError("recovery journal binding changed before clear")
        os.unlink(name, dir_fd=root_fd)
        os.fsync(root_fd)
    finally:
        os.close(root_fd)
    try:
        remove_recovery_marker(meetings_dir, binding.entry, binding.token)
    except Exception:
        LOGGER.exception("Cleared recovery journal left a harmless published marker")


def _binding_from_payload(
    payload: object,
    entry: RecoveryIndexEntry,
) -> tuple[RecoveryIndexEntry, str, PostCommitPolicy]:
    if not isinstance(payload, dict) or payload.get("version") != JOURNAL_VERSION:
        raise ValueError("recovery journal record is invalid")
    _validate_slot(payload, entry)
    digest = str(payload["source_sha256"])
    token = str(payload["token"])
    if len(digest) != 64 or len(token) != 32:
        raise ValueError("recovery journal provenance is invalid")
    pinned = replace(
        entry,
        source_device=int(payload["source_device"]),
        source_inode=int(payload["source_inode"]),
        source_size=int(payload["source_size"]),
        source_sha256=digest,
    )
    policy = PostCommitPolicy(
        payload.get("transcription") is True,
        payload.get("backup") is True,
    )
    return pinned, token, policy


def _record_payload(
    entry: RecoveryIndexEntry,
    token: str,
    policy: PostCommitPolicy,
) -> dict[str, object]:
    return {
        "version": JOURNAL_VERSION,
        "token": token,
        "origin": entry.origin.value,
        "session_directory": str(entry.session_directory),
        "session_device": entry.session_device,
        "session_inode": entry.session_inode,
        "source_name": entry.source_path.name,
        "source_device": entry.source_device,
        "source_inode": entry.source_inode,
        "source_size": entry.source_size,
        "source_sha256": entry.source_sha256,
        "transcription": policy.transcription,
        "backup": policy.backup,
    }


def _validate_slot(payload: dict[str, object], entry: RecoveryIndexEntry) -> None:
    expected = {
        "origin": entry.origin.value,
        "session_directory": str(entry.session_directory),
        "session_device": entry.session_device,
        "session_inode": entry.session_inode,
        "source_name": entry.source_path.name,
    }
    if any(payload.get(key) != value for key, value in expected.items()):
        raise ValueError("recovery journal source binding changed")


def _open_journal(meetings_dir: Path, *, create: bool = False) -> int:
    root = meetings_dir.expanduser()
    if create:
        root.mkdir(parents=True, exist_ok=True)
    canonical = root.resolve(strict=True)
    return open_directory_tree(
        canonical / ".meeting-memory-staging" / JOURNAL_DIRECTORY,
        create=create,
        require_private_final=True,
    )


def _record_name(entry: RecoveryIndexEntry) -> str:
    stable = "\0".join(
        (
            entry.origin.value,
            str(entry.session_directory),
            str(entry.session_device),
            str(entry.session_inode),
            entry.source_path.name,
        )
    )
    return f"{hashlib.sha256(stable.encode()).hexdigest()}.json"


def _require_provenance(entry: RecoveryIndexEntry) -> None:
    values = (entry.source_device, entry.source_inode, entry.source_size, entry.source_sha256)
    if any(value is None for value in values):
        raise ValueError("recovery journal requires complete source provenance")

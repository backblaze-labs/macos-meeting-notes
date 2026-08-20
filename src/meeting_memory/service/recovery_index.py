"""App-staging recovery index and explicit legacy discovery primitives."""

from __future__ import annotations

import json
import os
import stat
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from meeting_memory.service.atomic_io import (
    AtomicReplaceDurabilityUncertain,
    atomic_replace_text_at,
)
from meeting_memory.service.pinned_fs import (
    create_private_child,
    open_directory_tree,
    read_regular_text_at,
    same_open_directory,
)
from meeting_memory.service.recovery_provenance import (
    source_provenance_from_payload,
    source_sha256,
)
from meeting_memory.service.recovery_publication import publication_from_payload
from meeting_memory.types.audio import CaptureDiagnostics
from meeting_memory.types.meeting import MeetingMeta, validate_meeting_slug
from meeting_memory.types.recovery import (
    RecoveryIndexEntry,
    RecoveryOrigin,
)

INDEX_FILENAME = "recovery.json"
WAV_FILENAME = "recording.wav"


def create_recovery_session(staging_root: Path, meta: MeetingMeta) -> RecoveryIndexEntry:
    """Create a private unique session and atomically persist its recovery index."""

    _validate_meta(meta)
    root = _ensure_private_root(staging_root.expanduser())
    root_fd = open_directory_tree(root, require_private_final=True)
    name, session_fd = create_private_child(root_fd, "capture.")
    session = root / name
    index_path = session / INDEX_FILENAME
    wav_path = session / WAV_FILENAME
    payload = _index_payload(meta)
    try:
        atomic_replace_text_at(
            session_fd,
            INDEX_FILENAME,
            json.dumps(payload, sort_keys=True),
        )
        if not same_open_directory(session, session_fd):
            raise ValueError("recovery session changed while creating its index")
        session_info = os.fstat(session_fd)
    except AtomicReplaceDurabilityUncertain:
        raise
    except BaseException:
        try:
            os.unlink(INDEX_FILENAME, dir_fd=session_fd)
        except FileNotFoundError:
            # Rollback is idempotent if the index was never published or is gone.
            pass
        os.rmdir(name, dir_fd=root_fd)
        os.fsync(root_fd)
        raise
    finally:
        os.close(session_fd)
        os.close(root_fd)
    return RecoveryIndexEntry(
        session_directory=session,
        source_path=wav_path,
        index_path=index_path,
        meta=meta,
        origin=RecoveryOrigin.APP_STAGING,
        session_device=session_info.st_dev,
        session_inode=session_info.st_ino,
    )


def update_recovery_session_meta(
    entry: RecoveryIndexEntry,
    meta: MeetingMeta,
) -> RecoveryIndexEntry:
    """Durably update final capture metadata inside the same pinned session."""

    _validate_meta(meta)
    session_fd = open_directory_tree(entry.session_directory)
    try:
        info = os.fstat(session_fd)
        if (info.st_dev, info.st_ino) != (entry.session_device, entry.session_inode):
            raise ValueError("recovery session changed before metadata update")
        atomic_replace_text_at(
            session_fd,
            INDEX_FILENAME,
            json.dumps(_index_payload(meta, entry), sort_keys=True),
        )
        if not same_open_directory(entry.session_directory, session_fd):
            raise ValueError("recovery session changed during metadata update")
    finally:
        os.close(session_fd)
    return replace(entry, meta=meta)


def discover_indexed_recoveries(staging_root: Path) -> tuple[RecoveryIndexEntry, ...]:
    """Read direct-child session indexes without following links or writing state."""

    root = staging_root.expanduser()
    try:
        root_fd = open_directory_tree(root, require_private_final=True)
    except (OSError, ValueError):
        return ()
    try:
        entries = [
            entry
            for name in sorted(os.listdir(root_fd))
            if (entry := _indexed_entry(root_fd, root, name)) is not None
        ]
        return tuple(sorted(entries, key=lambda item: item.meta.started_at))
    finally:
        os.close(root_fd)


def pin_recovery_source(entry: RecoveryIndexEntry) -> RecoveryIndexEntry:
    """Capture the source identity after recording closes and before conversion."""

    if entry.source_path.parent != entry.session_directory:
        raise ValueError("recovery source must be inside its indexed session")
    session_fd = open_directory_tree(entry.session_directory)
    try:
        session_info = os.fstat(session_fd)
        if (session_info.st_dev, session_info.st_ino) != (
            entry.session_device,
            entry.session_inode,
        ):
            raise ValueError("recovery session was replaced before source pinning")
        descriptor = os.open(
            entry.source_path.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=session_fd,
        )
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size == 0:
            raise ValueError("recovery source must be a non-empty regular file")
        digest = source_sha256(descriptor, info.st_size)
    finally:
        if "descriptor" in locals():
            os.close(descriptor)
        os.close(session_fd)
    pinned = replace(
        entry,
        source_device=info.st_dev,
        source_inode=info.st_ino,
        source_size=info.st_size,
        source_sha256=digest,
    )
    if pinned.origin is RecoveryOrigin.APP_STAGING and pinned.index_path is not None:
        _persist_pinned_index(pinned)
    return pinned


def _ensure_private_root(root: Path) -> Path:
    descriptor = open_directory_tree(root, create=True, require_private_final=True)
    try:
        if not same_open_directory(root, descriptor):
            raise ValueError("recovery staging root changed while opening")
    finally:
        os.close(descriptor)
    return root


def _indexed_entry(root_fd: int, root: Path, name: str) -> RecoveryIndexEntry | None:
    session = root / name
    session_fd = -1
    try:
        session_fd = os.open(
            name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=root_fd,
        )
        session_info = os.fstat(session_fd)
        if stat.S_IMODE(session_info.st_mode) & 0o077:
            return None
        payload = json.loads(read_regular_text_at(session_fd, INDEX_FILENAME))
        if payload.get("version") != 1 or payload.get("wav_file") != WAV_FILENAME:
            return None
        meta = _meta_from_payload(payload)
        publication = publication_from_payload(payload.get("publication"))
        source_fd = os.open(
            WAV_FILENAME,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=session_fd,
        )
        try:
            source_info = os.fstat(source_fd)
        finally:
            os.close(source_fd)
        if not stat.S_ISREG(source_info.st_mode) or source_info.st_size == 0:
            return None
        provenance = source_provenance_from_payload(payload, source_info)
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError, UnicodeError):
        return None
    finally:
        if session_fd >= 0:
            os.close(session_fd)
    return RecoveryIndexEntry(
        session_directory=session,
        source_path=session / WAV_FILENAME,
        index_path=session / INDEX_FILENAME,
        meta=meta,
        origin=RecoveryOrigin.APP_STAGING,
        session_device=session_info.st_dev,
        session_inode=session_info.st_ino,
        source_device=(publication.source_device if publication else provenance[0]),
        source_inode=(publication.source_inode if publication else provenance[1]),
        source_size=(publication.source_size if publication else provenance[2]),
        source_sha256=(publication.source_sha256 if publication else provenance[3]),
        publication=publication,
    )


def _meta_from_payload(payload: dict[str, object]) -> MeetingMeta:
    slug = validate_meeting_slug(str(payload["slug"]))
    raw_candidates = payload.get("speaker_candidates", ())
    if not isinstance(raw_candidates, list) or not all(
        isinstance(item, str) for item in raw_candidates
    ):
        raise ValueError("recovery speaker_candidates must be a list of strings")
    return MeetingMeta(
        slug=slug,
        started_at=datetime.fromisoformat(str(payload["started_at"])),
        calendar_title=str(payload.get("calendar_title") or "Recovered Recording"),
        duration_minutes=int(payload.get("duration_minutes") or 0),
        speaker_candidates=tuple(raw_candidates),
        capture_diagnostics=(
            CaptureDiagnostics.from_payload(payload["capture_diagnostics"])
            if payload.get("capture_diagnostics") is not None
            else None
        ),
    )


def _validate_meta(meta: MeetingMeta) -> None:
    validate_meeting_slug(meta.slug)
    if not isinstance(meta.speaker_candidates, tuple) or not all(
        isinstance(item, str) for item in meta.speaker_candidates
    ):
        raise ValueError("recovery speaker_candidates must be a tuple of strings")


def _index_payload(
    meta: MeetingMeta,
    entry: RecoveryIndexEntry | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "version": 1,
        "wav_file": WAV_FILENAME,
        "slug": meta.slug,
        "started_at": meta.started_at.isoformat(),
        "calendar_title": meta.calendar_title,
        "duration_minutes": meta.duration_minutes,
        "speaker_candidates": list(meta.speaker_candidates),
    }
    if meta.capture_diagnostics is not None:
        payload["capture_diagnostics"] = meta.capture_diagnostics.to_payload()
    if entry is not None and all(
        value is not None
        for value in (
            entry.source_device,
            entry.source_inode,
            entry.source_size,
            entry.source_sha256,
        )
    ):
        payload["source"] = {
            "device": entry.source_device,
            "inode": entry.source_inode,
            "size": entry.source_size,
            "sha256": entry.source_sha256,
        }
    return payload


def _persist_pinned_index(entry: RecoveryIndexEntry) -> None:
    session_fd = open_directory_tree(entry.session_directory)
    try:
        info = os.fstat(session_fd)
        if (info.st_dev, info.st_ino) != (entry.session_device, entry.session_inode):
            raise ValueError("recovery session changed before provenance update")
        atomic_replace_text_at(
            session_fd,
            INDEX_FILENAME,
            json.dumps(_index_payload(entry.meta, entry), sort_keys=True),
        )
    finally:
        os.close(session_fd)

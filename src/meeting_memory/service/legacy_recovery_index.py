"""Explicit read-only once scan and durable state for legacy temp recovery."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import stat
import wave
from datetime import datetime
from fnmatch import fnmatchcase
from pathlib import Path

from meeting_memory.service.atomic_io import atomic_replace_text_at
from meeting_memory.service.pinned_fs import (
    open_directory_tree,
    read_regular_text_at,
)
from meeting_memory.types.meeting import MeetingMeta, validate_meeting_slug
from meeting_memory.types.recovery import (
    LegacyDiscoveryResult,
    LegacyDiscoveryState,
    RecoveryIndexEntry,
    RecoveryOrigin,
)

LEGACY_GLOB = "meeting-memory-*.wav"
LEGACY_M4A_GLOB = "meeting-memory-*.m4a"
LEGACY_MARKER_FILENAME = "legacy-recovery-scan.json"


def discover_legacy_once(
    legacy_temp_dir: Path,
    state: LegacyDiscoveryState,
) -> LegacyDiscoveryResult:
    """Perform at most one caller-authorized, read-only legacy temp scan."""

    if state.completed:
        return LegacyDiscoveryResult((), state)
    root = legacy_temp_dir.expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("legacy recovery root must resolve to a directory")
    entries: list[RecoveryIndexEntry] = []
    root_fd = open_directory_tree(root)
    try:
        for name in _legacy_candidates(root_fd):
            entry = _legacy_entry(root_fd, root, name)
            if entry is not None:
                entries.append(entry)
    finally:
        os.close(root_fd)
    return LegacyDiscoveryResult(tuple(entries), LegacyDiscoveryState(completed=True))


def load_legacy_discovery_state(marker_path: Path) -> LegacyDiscoveryState:
    try:
        parent_fd = open_directory_tree(marker_path.parent)
    except FileNotFoundError:
        return LegacyDiscoveryState()
    try:
        try:
            payload = json.loads(read_regular_text_at(parent_fd, marker_path.name))
        except FileNotFoundError:
            return LegacyDiscoveryState()
    finally:
        os.close(parent_fd)
    if payload != {"completed": True, "version": 1}:
        raise ValueError("legacy recovery marker is invalid")
    return LegacyDiscoveryState(completed=True)


def persist_legacy_discovery_complete(marker_path: Path) -> LegacyDiscoveryState:
    if marker_path.name != LEGACY_MARKER_FILENAME:
        raise ValueError(f"legacy marker must be named {LEGACY_MARKER_FILENAME}")
    parent_fd = open_directory_tree(
        marker_path.parent,
        create=True,
        require_private_final=True,
    )
    try:
        atomic_replace_text_at(
            parent_fd,
            marker_path.name,
            json.dumps({"completed": True, "version": 1}),
        )
    finally:
        os.close(parent_fd)
    return LegacyDiscoveryState(completed=True)


def _legacy_entry(root_fd: int, root: Path, name: str) -> RecoveryIndexEntry | None:
    source_path = root / name
    slug = source_path.stem.removeprefix("meeting-memory-")
    try:
        source_info = _nonempty_regular_info_at(root_fd, name)
        if source_info is None:
            return None
        source_digest = _source_sha256_at(root_fd, name, source_info.st_size)
        validate_meeting_slug(slug)
        duration = (
            _wav_duration_minutes_at(root_fd, name)
            if source_path.suffix == ".wav"
            else 0
        )
        if source_path.suffix == ".wav" and duration is None:
            return None
        started_at = datetime.strptime(slug[:16], "%Y-%m-%d_%H-%M").astimezone()
    except OSError as exc:
        if _is_unsafe_candidate_error(exc):
            return None
        raise
    except ValueError:
        return None
    title = slug[17:].replace("-", " ").strip().title() or "Recovered Recording"
    meta = MeetingMeta(slug, started_at, title, duration or 0)
    root_info = os.fstat(root_fd)
    return RecoveryIndexEntry(
        root,
        source_path,
        None,
        meta,
        RecoveryOrigin.LEGACY_TEMP,
        root_info.st_dev,
        root_info.st_ino,
        source_info.st_dev,
        source_info.st_ino,
        source_info.st_size,
        source_digest,
    )


def _legacy_candidates(root_fd: int) -> tuple[str, ...]:
    by_stem: dict[str, list[str]] = {}
    for name in sorted(os.listdir(root_fd)):
        if fnmatchcase(name, LEGACY_GLOB) or fnmatchcase(name, LEGACY_M4A_GLOB):
            by_stem.setdefault(Path(name).stem, []).append(name)
    selected: list[str] = []
    for stem in sorted(by_stem):
        ordered = sorted(by_stem[stem], key=lambda item: Path(item).suffix != ".m4a")
        valid = next(
            (name for name in ordered if _valid_legacy_candidate_at(root_fd, name)),
            None,
        )
        if valid is not None:
            selected.append(valid)
    return tuple(selected)


def _valid_legacy_candidate_at(root_fd: int, name: str) -> bool:
    try:
        if _nonempty_regular_info_at(root_fd, name) is None:
            return False
        return Path(name).suffix == ".m4a" or _wav_duration_minutes_at(root_fd, name) is not None
    except OSError as exc:
        if _is_unsafe_candidate_error(exc):
            return False
        raise


def _nonempty_regular_info_at(root_fd: int, name: str) -> os.stat_result | None:
    descriptor = os.open(
        name,
        os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
        dir_fd=root_fd,
    )
    try:
        info = os.fstat(descriptor)
        return info if stat.S_ISREG(info.st_mode) and info.st_size > 0 else None
    finally:
        os.close(descriptor)


def _wav_duration_minutes_at(root_fd: int, name: str) -> int | None:
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=root_fd,
        )
    except FileNotFoundError:
        return None
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            return None
        try:
            with wave.open(stream, "rb") as audio:
                frames, rate = audio.getnframes(), audio.getframerate()
                frame_size = audio.getnchannels() * audio.getsampwidth()
                first = audio.readframes(1)
        except (EOFError, wave.Error):
            return None
    if frames <= 0 or rate <= 0 or frame_size <= 0 or len(first) < frame_size:
        return None
    return max(0, round(frames / rate / 60))


def _is_unsafe_candidate_error(exc: OSError) -> bool:
    return exc.errno in {errno.ELOOP, errno.ENOENT, errno.ENOTDIR}


def _source_sha256_at(root_fd: int, name: str, size: int) -> str:
    descriptor = os.open(
        name,
        os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
        dir_fd=root_fd,
    )
    try:
        digest = hashlib.sha256()
        offset = 0
        while offset < size:
            chunk = os.pread(descriptor, min(1024 * 1024, size - offset), offset)
            if not chunk:
                break
            digest.update(chunk)
            offset += len(chunk)
        return digest.hexdigest()
    finally:
        os.close(descriptor)

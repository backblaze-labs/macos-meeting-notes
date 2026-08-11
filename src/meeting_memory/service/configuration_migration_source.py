"""Strict, stable, bounded reads for explicit legacy environment migration."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path

from dotenv.parser import parse_stream

from meeting_memory.types.configuration import SettingKey

MAX_MIGRATION_ENV_BYTES = 1_048_576


class MigrationSourceError(RuntimeError):
    """A legacy environment source was unsafe or malformed."""


@dataclass(frozen=True, slots=True)
class MigrationSourceFingerprint:
    """Private source identity; never place this object in a public preview."""

    device: int = field(repr=False)
    inode: int = field(repr=False)
    size: int = field(repr=False)
    modified_ns: int = field(repr=False)
    changed_ns: int = field(repr=False)
    sha256: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class MigrationSourceRead:
    """Ephemeral parsed values plus their stable private fingerprint."""

    values: dict[SettingKey, str] = field(repr=False)
    fingerprint: MigrationSourceFingerprint = field(repr=False)


def read_migration_source(path: Path) -> MigrationSourceRead | None:
    """Read one stable regular source, following a compatible final symlink."""

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        return None
    except Exception:
        raise MigrationSourceError("Legacy environment could not be read safely.") from None
    try:
        before = _validated_info(descriptor)
        content = _read_bounded(descriptor)
        after = _validated_info(descriptor)
        if _identity(before) != _identity(after) or len(content) != before.st_size:
            raise OSError("legacy environment changed during read")
        text = content.decode("utf-8")
        values = _strict_recognized_values(text)
        return MigrationSourceRead(values, _fingerprint(before, content))
    except Exception:
        raise MigrationSourceError("Legacy environment could not be read safely.") from None
    finally:
        os.close(descriptor)


def source_matches(path: Path, expected: MigrationSourceFingerprint) -> bool:
    """Reopen and compare the exact current source without exposing details."""

    try:
        current = read_migration_source(path)
        return current is not None and current.fingerprint == expected
    except Exception:
        return False


def _validated_info(descriptor: int):
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_MIGRATION_ENV_BYTES:
        raise OSError("legacy environment is not a bounded regular file")
    return info


def _read_bounded(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    remaining = MAX_MIGRATION_ENV_BYTES + 1
    while remaining:
        chunk = os.read(descriptor, min(65_536, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    content = b"".join(chunks)
    if len(content) > MAX_MIGRATION_ENV_BYTES:
        raise OSError("legacy environment is too large")
    return content


def _strict_recognized_values(content: str) -> dict[SettingKey, str]:
    parsed: dict[str, str] = {}
    recognized = {key.value for key in SettingKey}
    for binding in parse_stream(StringIO(content)):
        if binding.error:
            raise ValueError("legacy environment syntax is invalid")
        if binding.key is not None:
            if binding.key in recognized and binding.key in parsed:
                raise ValueError("legacy environment setting is duplicated")
            parsed[binding.key] = "" if binding.value is None else binding.value
    return {key: parsed[key.value] for key in SettingKey if key.value in parsed}


def _identity(info) -> tuple[int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _fingerprint(info, content: bytes) -> MigrationSourceFingerprint:
    return MigrationSourceFingerprint(
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
        hashlib.sha256(content).hexdigest(),
    )

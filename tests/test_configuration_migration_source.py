"""Adversarial source tests for explicit environment migration."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from meeting_memory.service import configuration_migration_source as source
from meeting_memory.service.configuration_migration_source import (
    MigrationSourceError,
    read_migration_source,
    source_matches,
)
from meeting_memory.types.configuration import SettingKey


def test_source_is_exact_strict_and_noninterpolating(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / ".env"
    original = (
        b"assemblyai_api_key=lower\n"
        b"assemblyai_api_key=lower-again\n"
        b"UNKNOWN=value\n"
        b"UNKNOWN=other\n"
        b"MEETINGS_DIR=${AMBIENT_SENTINEL}\n"
        b"ASSEMBLYAI_API_KEY=exact\n"
    )
    path.write_bytes(original)
    monkeypatch.setenv("AMBIENT_SENTINEL", "/private/ambient")

    result = read_migration_source(path)

    assert result is not None
    assert result.values == {
        SettingKey.MEETINGS_DIR: "${AMBIENT_SENTINEL}",
        SettingKey.ASSEMBLYAI_API_KEY: "exact",
    }
    assert path.read_bytes() == original
    assert source_matches(path, result.fingerprint)


def test_duplicate_recognized_key_fails_without_leaking_or_changing_source(
    tmp_path: Path,
    capsys,
) -> None:
    path = tmp_path / ".env"
    original = b"ASSEMBLYAI_API_KEY=secret-one\nASSEMBLYAI_API_KEY=secret-two\n"
    path.write_bytes(original)

    with pytest.raises(MigrationSourceError) as error:
        read_migration_source(path)

    captured = capsys.readouterr()
    public = f"{error.value!s} {captured.out} {captured.err}"
    assert "secret-one" not in public
    assert "secret-two" not in public
    assert path.read_bytes() == original


@pytest.mark.parametrize("content", [b"BROKEN='unterminated\n", b"BROKEN: syntax\n"])
def test_malformed_source_fails_whole_parse_without_warning_or_value_leak(
    tmp_path: Path,
    capsys,
    content: bytes,
) -> None:
    path = tmp_path / ".env"
    sentinel = b"secret-sentinel"
    path.write_bytes(b"ASSEMBLYAI_API_KEY=" + sentinel + b"\n" + content)

    with pytest.raises(MigrationSourceError) as error:
        read_migration_source(path)

    captured = capsys.readouterr()
    assert sentinel.decode() not in str(error.value)
    assert sentinel.decode() not in captured.out
    assert sentinel.decode() not in captured.err


@pytest.mark.parametrize("kind", ["fifo", "directory", "device", "oversize", "utf8"])
def test_nonregular_unbounded_or_non_utf8_sources_fail_sanitized_without_hanging(
    tmp_path: Path,
    monkeypatch,
    kind: str,
) -> None:
    path = tmp_path / ".env"
    if kind == "fifo":
        os.mkfifo(path)
    elif kind == "directory":
        path.mkdir()
    elif kind == "device":
        path = Path("/dev/null")
    elif kind == "oversize":
        monkeypatch.setattr(source, "MAX_MIGRATION_ENV_BYTES", 4)
        path.write_bytes(b"MEETINGS_DIR=/private")
    else:
        path.write_bytes(b"MEETINGS_DIR=\xff")

    with pytest.raises(MigrationSourceError) as error:
        read_migration_source(path)

    assert str(path) not in str(error.value)


def test_missing_source_is_empty_and_regular_symlink_is_preserved(tmp_path: Path) -> None:
    missing = tmp_path / "missing.env"
    assert read_migration_source(missing) is None

    target = tmp_path / "legacy.env"
    linked = tmp_path / ".env"
    original = b"MEETINGS_DIR=~/Meetings\n"
    target.write_bytes(original)
    linked.symlink_to(target)

    result = read_migration_source(linked)

    assert result is not None
    assert linked.is_symlink()
    assert linked.readlink() == target
    assert target.read_bytes() == original


def test_same_size_mutation_invalidates_fingerprint(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_bytes(b"MEETINGS_DIR=/first\n")
    result = read_migration_source(path)
    assert result is not None

    path.write_bytes(b"MEETINGS_DIR=/other\n")

    assert source_matches(path, result.fingerprint) is False


def test_source_change_during_read_is_rejected(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / ".env"
    path.write_bytes(b"MEETINGS_DIR=/private\n")
    original_read = source.os.read
    changed = False

    def changing_read(descriptor: int, size: int) -> bytes:
        nonlocal changed
        chunk = original_read(descriptor, size)
        if chunk and not changed:
            changed = True
            path.chmod(0o600)
        return chunk

    monkeypatch.setattr(source.os, "read", changing_read)

    with pytest.raises(MigrationSourceError):
        read_migration_source(path)

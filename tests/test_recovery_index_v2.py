"""Inactive indexed-recovery primitive tests."""

from __future__ import annotations

import json
import shutil
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from meeting_memory.service.meeting_store import MeetingStore
from meeting_memory.service.recovery_cleanup import cleanup_recovery_after_commit
from meeting_memory.service.recovery_commit import commit_recovery
from meeting_memory.service.recovery_index import (
    INDEX_FILENAME,
    create_recovery_session,
    discover_indexed_recoveries,
    pin_recovery_source,
)
from meeting_memory.types.meeting import MeetingMeta


def test_create_is_private_unique_atomic_and_discovery_is_read_only(tmp_path: Path) -> None:
    root = tmp_path / "private" / "staging"
    first = create_recovery_session(root, _meta())
    second = create_recovery_session(root, _meta("2026-08-10_10-01_second"))
    assert first.session_directory != second.session_directory
    assert first.session_directory.stat().st_mode & 0o077 == 0
    assert json.loads(first.index_path.read_text())["wav_file"] == "recording.wav"
    first.source_path.write_bytes(b"wav data")
    before = _tree_times(root)

    entries = discover_indexed_recoveries(root)

    assert [entry.meta.slug for entry in entries] == [first.meta.slug]
    assert entries[0].source_device is not None
    assert _tree_times(root) == before


@pytest.mark.parametrize(
    "meta",
    [
        MeetingMeta("../escape", datetime.now(UTC)),
        MeetingMeta("2026-08-10_10-00_bad", datetime.now(UTC), speaker_candidates="A"),
    ],
)
def test_invalid_metadata_is_rejected_before_staging_creation(
    tmp_path: Path, meta: MeetingMeta
) -> None:
    root = tmp_path / "staging"
    with pytest.raises(ValueError):
        create_recovery_session(root, meta)
    assert not root.exists()


def test_recovery_root_rejects_broad_shared_and_intermediate_symlink(
    tmp_path: Path,
) -> None:
    shared = tmp_path / "shared"
    shared.mkdir(mode=0o777)
    shared.chmod(0o777)
    original_mode = shared.stat().st_mode & 0o777
    with pytest.raises(ValueError, match="unsafe permissions"):
        create_recovery_session(shared, _meta())
    assert shared.stat().st_mode & 0o777 == original_mode
    assert not any(shared.iterdir())
    with pytest.raises(ValueError, match="filesystem root"):
        create_recovery_session(Path("/"), _meta())

    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "link"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        create_recovery_session(link / "staging", _meta())
    assert not any(outside.iterdir())
    assert discover_indexed_recoveries(link / "staging") == ()


def test_discovery_rejects_symlink_index_and_source_without_suppressing_others(
    tmp_path: Path,
) -> None:
    root = tmp_path / "staging"
    valid = create_recovery_session(root, _meta())
    valid.source_path.write_bytes(b"valid")
    bad = create_recovery_session(root, _meta("2026-08-10_10-02_bad"))
    bad.index_path.unlink()
    bad.index_path.symlink_to(valid.index_path)
    bad.source_path.symlink_to(valid.source_path)
    linked_session = root / "capture.link"
    linked_session.symlink_to(valid.session_directory, target_is_directory=True)

    assert [item.meta.slug for item in discover_indexed_recoveries(root)] == [valid.meta.slug]


def test_cleanup_occurs_only_after_valid_commit_and_checks_source_identity(
    tmp_path: Path,
) -> None:
    root = tmp_path / "staging"
    entry = _pinned_entry(root, _meta(), b"captured audio")
    result = commit_recovery(
        MeetingStore(tmp_path / "meetings"), entry, validate_m4a=_validate_aac
    )
    committed, receipt = result.files, result.receipt

    replacement = entry.source_path.with_name("original.wav")
    entry.source_path.rename(replacement)
    entry.source_path.write_bytes(b"replacement")
    with pytest.raises(ValueError, match="source changed"):
        cleanup_recovery_after_commit(receipt)
    assert entry.source_path.read_bytes() == b"replacement"
    assert committed.audio_path.read_bytes() == _m4a(b"captured audio")

    entry.source_path.unlink()
    replacement.rename(entry.source_path)
    cleanup_recovery_after_commit(receipt)
    assert not entry.session_directory.exists()


def test_cleanup_preserves_replaced_session(tmp_path: Path) -> None:
    entry = _pinned_entry(tmp_path / "staging", _meta(), b"captured audio")
    result = commit_recovery(
        MeetingStore(tmp_path / "meetings"), entry, validate_m4a=_validate_aac
    )
    receipt = result.receipt
    moved = entry.session_directory.with_name("original-session")
    entry.session_directory.rename(moved)
    entry.session_directory.mkdir(mode=0o700)
    (entry.session_directory / entry.source_path.name).write_bytes(b"replacement")
    (entry.session_directory / INDEX_FILENAME).write_text("replacement")

    with pytest.raises(ValueError, match="session was replaced"):
        cleanup_recovery_after_commit(receipt)

    assert (entry.session_directory / entry.source_path.name).read_bytes() == b"replacement"
    assert moved.exists()


def test_receipt_cannot_target_an_unrelated_recovery(tmp_path: Path) -> None:
    root = tmp_path / "staging"
    first = _pinned_entry(root, _meta("2026-08-10_10-10_first"), b"first")
    second = _pinned_entry(root, _meta("2026-08-10_10-11_second"), b"second")
    store = MeetingStore(tmp_path / "meetings")
    first_result = commit_recovery(store, first, validate_m4a=_validate_aac)
    second_result = commit_recovery(store, second, validate_m4a=_validate_aac)

    cleanup_recovery_after_commit(second_result.receipt)
    assert first.source_path.read_bytes() == _m4a(b"first")
    assert not second.session_directory.exists()

    cleanup_recovery_after_commit(first_result.receipt)
    assert not first.session_directory.exists()


def test_replaced_committed_directory_rejects_cleanup(tmp_path: Path) -> None:
    entry = _pinned_entry(tmp_path / "staging", _meta(), b"captured")
    result = commit_recovery(
        MeetingStore(tmp_path / "meetings"), entry, validate_m4a=_validate_aac
    )
    committed, receipt = result.files, result.receipt
    original = committed.directory.with_name("published-original")
    committed.directory.rename(original)
    shutil.copytree(original, committed.directory)

    with pytest.raises(ValueError, match="committed directory was replaced"):
        cleanup_recovery_after_commit(receipt)

    assert entry.source_path.read_bytes() == _m4a(b"captured")
    assert committed.audio_path.read_bytes() == _m4a(b"captured")


def test_commit_rejects_replaced_source_even_with_same_metadata(tmp_path: Path) -> None:
    entry = _pinned_entry(tmp_path / "staging", _meta(), b"first bytes")
    moved = entry.source_path.with_name("original.wav")
    entry.source_path.rename(moved)
    entry.source_path.write_bytes(b"different bytes")

    with pytest.raises(ValueError, match="source changed before commit"):
        commit_recovery(
            MeetingStore(tmp_path / "meetings"), entry, validate_m4a=_validate_aac
        )

    assert entry.source_path.read_bytes() == b"different bytes"
    assert moved.read_bytes() == _m4a(b"first bytes")
    assert not (tmp_path / "meetings").exists()


def test_commit_rejects_changed_bytes_on_the_same_pinned_inode(tmp_path: Path) -> None:
    entry = _pinned_entry(tmp_path / "staging", _meta(), b"first bytes")
    original_inode = entry.source_path.stat().st_ino
    entry.source_path.write_bytes(b"different bytes")
    assert entry.source_path.stat().st_ino == original_inode

    with pytest.raises(ValueError, match="source changed before commit"):
        commit_recovery(
            MeetingStore(tmp_path / "meetings"), entry, validate_m4a=_validate_aac
        )

    assert entry.source_path.read_bytes() == b"different bytes"
    assert not (tmp_path / "meetings").exists()


def test_recovery_commit_accepts_collision_suffixes_through_three_digits(
    tmp_path: Path,
) -> None:
    root = tmp_path / "staging"
    store = MeetingStore(tmp_path / "meetings")
    results = [
        commit_recovery(
            store,
            _pinned_entry(root, _meta(), f"audio-{index}".encode()),
            validate_m4a=_validate_aac,
        )
        for index in range(100)
    ]

    assert results[0].files.meta.slug == _meta().slug
    assert results[9].files.meta.slug == f"{_meta().slug}-10"
    assert results[10].files.meta.slug == f"{_meta().slug}-11"
    assert results[99].files.meta.slug == f"{_meta().slug}-100"
    for result in results:
        cleanup_recovery_after_commit(result.receipt)


def _meta(slug: str = "2026-08-10_10-00_atomic") -> MeetingMeta:
    return MeetingMeta(slug, datetime(2026, 8, 10, 10, tzinfo=UTC), "Atomic", 2)


def _pinned_entry(root: Path, meta: MeetingMeta, content: bytes):
    entry = create_recovery_session(root, meta)
    source = entry.source_path.with_suffix(".m4a")
    entry = replace(entry, source_path=source)
    source.write_bytes(_m4a(content))
    return pin_recovery_source(entry)


def _m4a(content: bytes) -> bytes:
    return b"TEST-M4A\0AAC\0" + content


def _validate_aac(path: Path) -> None:
    if not path.read_bytes().startswith(b"TEST-M4A\0AAC\0"):
        raise ValueError("test validator rejected M4A without AAC audio")


def _tree_times(root: Path) -> dict[Path, int]:
    return {path: path.stat().st_mtime_ns for path in (root, *root.iterdir())}

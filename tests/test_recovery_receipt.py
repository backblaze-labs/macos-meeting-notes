"""Sealed cleanup-capability and final-artifact provenance tests."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from meeting_memory.service.meeting_store import MeetingStore
from meeting_memory.service.recovery_cleanup import cleanup_recovery_after_commit
from meeting_memory.service.recovery_commit import (
    RecoveryCleanupReceipt,
    RecoveryCommitCleanupUncertain,
    RecoveryCommitDurabilityUncertain,
    commit_recovery,
)
from meeting_memory.service.recovery_index import (
    create_recovery_session,
    pin_recovery_source,
)
from meeting_memory.types.meeting import MeetingMeta


def test_cleanup_receipt_cannot_be_forged_or_replaced_by_plain_data(
    tmp_path: Path,
) -> None:
    entry = _entry(tmp_path)
    with pytest.raises(TypeError, match="only be issued"):
        RecoveryCleanupReceipt(  # type: ignore[arg-type]
            object(), entry, None, None, False
        )
    with pytest.raises(TypeError, match="commit-issued"):
        cleanup_recovery_after_commit(object())  # type: ignore[arg-type]
    assert entry.source_path.exists()


@pytest.mark.parametrize("mutation", ["truncate", "replace"])
def test_changed_final_audio_preserves_recovery_source(
    tmp_path: Path,
    mutation: str,
) -> None:
    entry = _entry(tmp_path)
    result = commit_recovery(
        MeetingStore(tmp_path / "meetings"),
        entry,
        validate_m4a=_validate_aac,
    )
    audio = result.files.audio_path
    if mutation == "truncate":
        audio.write_bytes(b"short")
    else:
        original = audio.with_name("published-original.m4a")
        audio.rename(original)
        audio.write_bytes(original.read_bytes())

    with pytest.raises(ValueError, match="committed audio changed"):
        cleanup_recovery_after_commit(result.receipt)

    assert entry.source_path.exists()
    assert entry.index_path is not None and entry.index_path.exists()


def test_receipt_binds_exact_published_audio_and_allows_cleanup(tmp_path: Path) -> None:
    entry = _entry(tmp_path)
    result = commit_recovery(
        MeetingStore(tmp_path / "meetings"),
        entry,
        validate_m4a=_validate_aac,
    )
    receipt = result.receipt
    info = result.files.audio_path.stat()
    content = result.files.audio_path.read_bytes()

    assert (receipt.audio_device, receipt.audio_inode) == (info.st_dev, info.st_ino)
    assert receipt.audio_size == len(content)
    assert receipt.audio_sha256 == hashlib.sha256(content).hexdigest()

    cleanup_recovery_after_commit(receipt)
    assert not entry.session_directory.exists()


def test_post_publish_source_close_failure_carries_result_and_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = _entry(tmp_path)
    from meeting_memory.service import recovery_commit

    real_close = recovery_commit._close_source

    def close_then_fail(descriptor: int) -> None:
        real_close(descriptor)
        raise OSError("injected source close failure")

    monkeypatch.setattr(recovery_commit, "_close_source", close_then_fail)

    with pytest.raises(RecoveryCommitCleanupUncertain) as caught:
        commit_recovery(
            MeetingStore(tmp_path / "meetings"),
            entry,
            validate_m4a=_validate_aac,
        )

    result = caught.value.result
    assert result.files.audio_path.exists()
    assert result.receipt.audio_sha256
    assert entry.source_path.exists()
    cleanup_recovery_after_commit(result.receipt)
    assert not entry.session_directory.exists()


def test_durability_and_source_close_failure_preserve_primary_and_block_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = _entry(tmp_path)
    meetings = tmp_path / "meetings"
    meetings.mkdir()
    (meetings / ".meeting-memory-staging").mkdir()

    def fail_final_sync(path: Path) -> None:
        if path == meetings:
            raise OSError("injected parent durability failure")

    from meeting_memory.service import recovery_commit

    real_close = recovery_commit._close_source

    def close_then_fail(descriptor: int) -> None:
        real_close(descriptor)
        raise OSError("injected source close failure")

    monkeypatch.setattr(recovery_commit, "_close_source", close_then_fail)
    store = MeetingStore(meetings, directory_sync=fail_final_sync)

    with pytest.raises(RecoveryCommitDurabilityUncertain) as caught:
        commit_recovery(store, entry, validate_m4a=_validate_aac)

    outcome = caught.value
    assert outcome.durability_uncertain
    assert outcome.cleanup_error is not None
    assert "source close failure" in str(outcome.cleanup_error)
    assert outcome.result.files.audio_path.exists()
    with pytest.raises(ValueError, match="durability is uncertain"):
        cleanup_recovery_after_commit(outcome.result.receipt)
    assert entry.source_path.exists()


def _entry(tmp_path: Path):
    meta = MeetingMeta(
        "2026-08-10_10-00_receipt",
        datetime(2026, 8, 10, 10, tzinfo=UTC),
        "Receipt",
        1,
    )
    entry = create_recovery_session(tmp_path / "staging", meta)
    source = entry.source_path.with_suffix(".m4a")
    source.write_bytes(b"TEST-M4A\0AAC\0audio")
    return pin_recovery_source(replace(entry, source_path=source))


def _validate_aac(path: Path) -> None:
    if not path.read_bytes().startswith(b"TEST-M4A\0AAC\0"):
        raise ValueError("test validator requires AAC")

"""Failure-boundary tests for the pre-publication recovery journal."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from meeting_memory.service import local_commit, recovery_journal
from meeting_memory.service.local_commit import LocalRecordingCommitter
from meeting_memory.service.meeting_store import MeetingStore
from meeting_memory.service.recovery_index import create_recovery_session, pin_recovery_source
from meeting_memory.types.events import RecordingCleanupPending, RecordingCommitted
from meeting_memory.types.meeting import MeetingMeta


def test_journal_failure_happens_before_publication(tmp_path: Path, monkeypatch) -> None:
    entry, meta = _entry(tmp_path)
    meetings = tmp_path / "meetings-journal-failure"
    events: list[object] = []
    monkeypatch.setattr(
        recovery_journal,
        "atomic_replace_text_at",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("journal fsync failed")),
    )
    committer = _committer(meetings, events)

    with pytest.raises(OSError, match="journal fsync failed"):
        committer.commit(entry, meta)

    assert entry.source_path.exists()
    assert not (meetings / meta.slug).exists()
    assert events == []


def test_marker_failure_removes_internal_stage_copy_but_keeps_source(
    tmp_path: Path,
    monkeypatch,
) -> None:
    entry, meta = _entry(tmp_path)
    meetings = tmp_path / "meetings-marker-failure"
    monkeypatch.setattr(
        local_commit,
        "write_recovery_marker",
        lambda *_args: (_ for _ in ()).throw(OSError("marker fsync failed")),
    )
    committer = _committer(meetings, [])

    with pytest.raises(OSError, match="marker fsync failed"):
        committer.commit(entry, meta)

    assert entry.source_path.exists()
    assert not (meetings / meta.slug).exists()
    staging_children = list((meetings / ".meeting-memory-staging").iterdir())
    assert [path.name for path in staging_children] == ["recovery-journal"]


def test_cleanup_failure_blocks_success_and_workers_until_exact_retry(
    tmp_path: Path,
    monkeypatch,
) -> None:
    entry, meta = _entry(tmp_path)
    meetings = tmp_path / "meetings-cleanup"
    real_cleanup = local_commit.cleanup_recovery_after_commit
    cleanup_calls = 0

    def fail_once(receipt) -> None:
        nonlocal cleanup_calls
        cleanup_calls += 1
        if cleanup_calls == 1:
            raise OSError("cleanup failed")
        real_cleanup(receipt)

    monkeypatch.setattr(local_commit, "cleanup_recovery_after_commit", fail_once)
    events: list[object] = []
    launches: list[object] = []
    committer = _committer(meetings, events, launches)

    assert committer.commit(entry, meta) is None
    assert [type(event) for event in events] == [RecordingCleanupPending]
    assert launches == []
    assert entry.source_path.exists()

    files = committer.commit(entry, meta)

    assert files is not None and files.directory == meetings / meta.slug
    assert [type(event) for event in events] == [
        RecordingCleanupPending,
        RecordingCommitted,
    ]
    assert len(launches) == 1
    assert not (meetings / f"{meta.slug}-2").exists()


def test_journal_clear_failure_after_cleanup_does_not_block_success(
    tmp_path: Path,
    monkeypatch,
) -> None:
    entry, meta = _entry(tmp_path)
    meetings = tmp_path / "meetings-clear-failure"
    events: list[object] = []
    launches: list[object] = []
    monkeypatch.setattr(
        local_commit,
        "clear_recovery_binding",
        lambda *_args: (_ for _ in ()).throw(OSError("journal clear failed")),
    )
    committer = _committer(meetings, events, launches)

    files = committer.commit(entry, meta)

    assert files is not None and files.directory == meetings / meta.slug
    assert [type(event) for event in events] == [RecordingCommitted]
    assert len(launches) == 1
    assert not entry.session_directory.exists()


def _entry(tmp_path: Path):
    meta = MeetingMeta(
        "2026-08-10_10-00_product-sync",
        datetime(2026, 8, 10, 10, tzinfo=UTC),
        "Product Sync",
    )
    entry = create_recovery_session(tmp_path / "staging", meta)
    entry.source_path.write_bytes(b"RIFF\x00\x00\x00\x00WAVEsamples")
    return pin_recovery_source(entry), meta


def _committer(meetings: Path, events: list[object], launches=None):
    return LocalRecordingCommitter(
        MeetingStore(meetings),
        events.append,
        converter=lambda _wav, output: output.write_bytes(b"m4a"),
        validate_m4a=lambda _path: None,
        post_commit_launcher=(
            (lambda files, policy: launches.append((files, policy)))
            if launches is not None
            else None
        ),
    )

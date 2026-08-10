"""Explicit legacy recovery runtime tests."""

from __future__ import annotations

from pathlib import Path

from meeting_memory.service import runtime_legacy_recovery
from meeting_memory.service.legacy_recovery_index import (
    LEGACY_MARKER_FILENAME,
    load_legacy_discovery_state,
)
from meeting_memory.service.local_commit import LocalRecordingCommitter
from meeting_memory.service.meeting_store import MeetingStore
from meeting_memory.service.runtime_legacy_recovery import LegacyRecoveryRuntime
from meeting_memory.types.events import NotifyEvent, RecordingCommitted
from meeting_memory.types.meeting import PostCommitPolicy


def test_legacy_runtime_does_not_scan_or_create_marker_at_construction(tmp_path: Path) -> None:
    legacy_root = tmp_path / "legacy"
    legacy_root.mkdir()
    marker = tmp_path / "state" / LEGACY_MARKER_FILENAME

    runtime = _runtime(legacy_root, marker, tmp_path / "meetings", [])

    assert runtime.entries == ()
    assert not marker.exists()


def test_successful_empty_scan_is_durably_once_only(tmp_path: Path) -> None:
    legacy_root = tmp_path / "legacy"
    legacy_root.mkdir()
    marker = tmp_path / "state" / LEGACY_MARKER_FILENAME
    events: list[object] = []
    runtime = _runtime(legacy_root, marker, tmp_path / "meetings", events)

    runtime.start_scan()

    assert load_legacy_discovery_state(marker).completed
    assert runtime.entries == ()
    assert events == [
        NotifyEvent(
            "Legacy recovery scan complete",
            "No legacy recordings found.",
            rebuild_menu=True,
        )
    ]


def test_marker_uses_private_child_under_shared_meeting_staging(tmp_path: Path) -> None:
    legacy_root = tmp_path / "legacy"
    legacy_root.mkdir()
    meetings = tmp_path / "meetings"
    staging = meetings / ".meeting-memory-staging"
    staging.mkdir(parents=True, mode=0o755)
    staging.chmod(0o755)
    marker = staging / "legacy-recovery" / LEGACY_MARKER_FILENAME
    runtime = _runtime(legacy_root, marker, meetings, [])

    runtime.start_scan()

    assert marker.is_file()
    assert marker.parent.stat().st_mode & 0o077 == 0
    assert staging.stat().st_mode & 0o077 == 0o055


def test_discoveries_remain_unmarked_until_every_explicit_commit(tmp_path: Path) -> None:
    legacy_root = tmp_path / "legacy"
    legacy_root.mkdir()
    first = legacy_root / "meeting-memory-2026-08-10_10-00_first.m4a"
    second = legacy_root / "meeting-memory-2026-08-10_10-01_second.m4a"
    first.write_bytes(b"first m4a")
    second.write_bytes(b"second m4a")
    marker = tmp_path / "state" / LEGACY_MARKER_FILENAME
    meetings = tmp_path / "meetings"
    events: list[object] = []
    policies: list[PostCommitPolicy] = []
    runtime = _runtime(legacy_root, marker, meetings, events, policies=policies)

    runtime.start_scan()
    discovered = runtime.entries
    assert len(discovered) == 2
    assert not marker.exists()
    assert policies == []

    runtime.start_commit(discovered[0])

    assert len(runtime.entries) == 1
    assert not marker.exists()
    assert not first.exists()
    assert second.exists()

    runtime.start_commit(discovered[1])

    assert runtime.entries == ()
    assert load_legacy_discovery_state(marker).completed
    assert not second.exists()
    assert policies == [PostCommitPolicy(), PostCommitPolicy()]
    assert sum(isinstance(event, RecordingCommitted) for event in events) == 2


def test_failed_explicit_commit_keeps_entry_source_and_marker(tmp_path: Path) -> None:
    legacy_root = tmp_path / "legacy"
    legacy_root.mkdir()
    source = legacy_root / "meeting-memory-2026-08-10_10-00_retry.m4a"
    source.write_bytes(b"retry m4a")
    marker = tmp_path / "state" / LEGACY_MARKER_FILENAME
    events: list[object] = []
    runtime = LegacyRecoveryRuntime(
        legacy_root,
        marker,
        NullCommitter(),
        events.append,
        thread_factory=ImmediateThread,
    )

    runtime.start_scan()
    entry = runtime.entries[0]
    runtime.start_commit(entry)

    assert runtime.entries == (entry,)
    assert source.exists()
    assert not marker.exists()


def test_marker_failure_after_commit_removes_stale_entry_and_allows_rescan(
    tmp_path: Path,
    monkeypatch,
) -> None:
    legacy_root = tmp_path / "legacy"
    legacy_root.mkdir()
    source = legacy_root / "meeting-memory-2026-08-10_10-00_saved.m4a"
    source.write_bytes(b"saved m4a")
    marker = tmp_path / "state" / LEGACY_MARKER_FILENAME
    meetings = tmp_path / "meetings"
    events: list[object] = []
    runtime = _runtime(legacy_root, marker, meetings, events)
    runtime.start_scan()
    entry = runtime.entries[0]
    real_persist = runtime_legacy_recovery.persist_legacy_discovery_complete
    calls = 0

    def fail_once(path):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("marker fsync failed")
        real_persist(path)

    monkeypatch.setattr(
        runtime_legacy_recovery,
        "persist_legacy_discovery_complete",
        fail_once,
    )
    runtime.start_commit(entry)

    assert runtime.entries == ()
    assert not source.exists()
    assert not marker.exists()
    runtime.start_scan()
    assert load_legacy_discovery_state(marker).completed


def _runtime(
    legacy_root: Path,
    marker: Path,
    meetings: Path,
    events: list[object],
    *,
    policies: list[PostCommitPolicy] | None = None,
) -> LegacyRecoveryRuntime:
    observed = policies if policies is not None else []
    committer = LocalRecordingCommitter(
        MeetingStore(meetings),
        events.append,
        converter=lambda source, output: output.write_bytes(source.read_bytes()),
        validate_m4a=lambda _path: None,
        policy_provider=PostCommitPolicy,
        post_commit_launcher=lambda _files, policy: observed.append(policy),
    )
    return LegacyRecoveryRuntime(
        legacy_root,
        marker,
        committer,
        events.append,
        thread_factory=ImmediateThread,
    )


class NullCommitter:
    def commit(self, _entry, _meta):
        return None


class ImmediateThread:
    def __init__(self, *, target, args=(), daemon=True):
        self.target = target
        self.args = args

    def start(self) -> None:
        self.target(*self.args)

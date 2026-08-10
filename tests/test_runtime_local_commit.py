from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from meeting_memory.service import local_commit, recovery_commit
from meeting_memory.service.legacy_recovery_index import discover_legacy_once
from meeting_memory.service.local_commit import LocalRecordingCommitter
from meeting_memory.service.meeting_store import MeetingStore
from meeting_memory.service.recovery_index import (
    create_recovery_session,
    discover_indexed_recoveries,
    pin_recovery_source,
)
from meeting_memory.types.events import (
    RecordingCommitted,
    RecordingPublicationUncertain,
)
from meeting_memory.types.meeting import MeetingMeta, PostCommitPolicy
from meeting_memory.types.recovery import LegacyDiscoveryState


def _entry(tmp_path: Path):
    meta = MeetingMeta(
        "2026-08-10_10-00_product-sync",
        datetime(2026, 8, 10, 10, tzinfo=UTC),
        "Product Sync",
    )
    entry = create_recovery_session(tmp_path / "staging", meta)
    entry.source_path.write_bytes(b"RIFF\x00\x00\x00\x00WAVE" + b"samples")
    return pin_recovery_source(entry), meta


def test_commit_event_cleanup_and_optional_launch_have_strict_order(
    tmp_path: Path,
    monkeypatch,
) -> None:
    entry, meta = _entry(tmp_path)
    order: list[str] = []
    policies: list[PostCommitPolicy] = []
    policy = PostCommitPolicy(transcription=True, backup=True)

    def cleanup(receipt) -> None:
        assert receipt.entry.source_path.exists()
        order.append("cleanup")

    monkeypatch.setattr(local_commit, "cleanup_recovery_after_commit", cleanup)
    committer = LocalRecordingCommitter(
        MeetingStore(tmp_path / "meetings"),
        lambda event: order.append("event") if isinstance(event, RecordingCommitted) else None,
        converter=lambda _wav, m4a: m4a.write_bytes(b"m4a"),
        validate_m4a=lambda _path: None,
        policy_provider=lambda: policy,
        post_commit_launcher=lambda _files, captured: (
            policies.append(captured), order.append("workers")
        ),
    )

    files = committer.commit(entry, meta)

    assert files is not None
    assert order == ["cleanup", "event", "workers"]
    assert policies == [policy]
    assert files.transcript_path.is_file()
    assert files.audio_path.read_bytes() == b"m4a"
    assert {path.name for path in files.directory.iterdir()} == {
        "recording.m4a",
        "transcript.md",
    }


def test_conversion_failure_preserves_recovery_and_emits_nothing(tmp_path: Path) -> None:
    entry, meta = _entry(tmp_path)
    events: list[object] = []
    launches: list[object] = []
    committer = LocalRecordingCommitter(
        MeetingStore(tmp_path / "meetings"),
        events.append,
        converter=lambda _wav, _m4a: (_ for _ in ()).throw(RuntimeError("failed")),
        validate_m4a=lambda _path: None,
        post_commit_launcher=lambda files, policy: launches.append((files, policy)),
    )

    with pytest.raises(RuntimeError, match="failed"):
        committer.commit(entry, meta)

    assert entry.source_path.is_file()
    assert entry.index_path.is_file()
    assert events == []
    assert launches == []
    assert not (tmp_path / "meetings" / meta.slug).exists()


def test_published_cleanup_uncertain_continues_event_cleanup_workers(
    tmp_path: Path,
    monkeypatch,
) -> None:
    entry, meta = _entry(tmp_path)
    observed: list[str] = []
    real_close = recovery_commit._close_source

    def close_then_fail(descriptor: int) -> None:
        real_close(descriptor)
        raise OSError("close failed after publish")

    monkeypatch.setattr(recovery_commit, "_close_source", close_then_fail)
    committer = LocalRecordingCommitter(
        MeetingStore(tmp_path / "meetings"),
        lambda event: observed.append("event")
        if isinstance(event, RecordingCommitted)
        else None,
        converter=lambda _wav, output: output.write_bytes(b"m4a"),
        validate_m4a=lambda _path: None,
        post_commit_launcher=lambda _files, _policy: observed.append("workers"),
    )

    files = committer.commit(entry, meta)

    assert files is not None
    assert observed == ["event", "workers"]
    assert not entry.session_directory.exists()


def test_durability_uncertain_persists_exact_reconciliation_without_duplicate(
    tmp_path: Path,
) -> None:
    entry, meta = _entry(tmp_path)
    meetings = tmp_path / "meetings"
    meetings.mkdir()
    (meetings / ".meeting-memory-staging").mkdir()
    events: list[object] = []
    launches: list[object] = []

    def fail_parent_sync(path: Path) -> None:
        if path == meetings:
            raise OSError("parent fsync failed")

    uncertain = LocalRecordingCommitter(
        MeetingStore(meetings, directory_sync=fail_parent_sync),
        events.append,
        converter=lambda _wav, output: output.write_bytes(b"m4a"),
        validate_m4a=lambda _path: None,
        post_commit_launcher=lambda files, policy: launches.append((files, policy)),
    )

    assert uncertain.commit(entry, meta) is None

    assert len(events) == 1
    assert isinstance(events[0], RecordingPublicationUncertain)
    assert launches == []
    assert entry.source_path.exists()
    recovered = discover_indexed_recoveries(entry.session_directory.parent)
    assert len(recovered) == 1
    assert (meetings / meta.slug).is_dir()

    committed_events: list[object] = []
    reconciled_launches: list[object] = []
    reconciler = LocalRecordingCommitter(
        MeetingStore(meetings),
        committed_events.append,
        converter=lambda *_args: (_ for _ in ()).throw(AssertionError("converted twice")),
        validate_m4a=lambda *_args: (_ for _ in ()).throw(AssertionError("validated twice")),
        post_commit_launcher=lambda files, policy: reconciled_launches.append(
            (files, policy)
        ),
    )

    files = reconciler.commit(entry, entry.meta)

    assert files is not None and files.directory == meetings / meta.slug
    assert len(committed_events) == 1
    assert isinstance(committed_events[0], RecordingCommitted)
    assert len(reconciled_launches) == 1
    assert not entry.session_directory.exists()
    assert not (meetings / f"{meta.slug}-2").exists()


def test_legacy_durability_uncertain_reconciles_without_suffix(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    source = legacy / "meeting-memory-2026-08-10_10-00_legacy.m4a"
    source.write_bytes(b"legacy-audio")
    entry = discover_legacy_once(legacy, LegacyDiscoveryState()).entries[0]
    meetings = tmp_path / "meetings-legacy"
    meetings.mkdir()
    (meetings / ".meeting-memory-staging").mkdir()
    events: list[object] = []

    def fail_parent_sync(path: Path) -> None:
        if path == meetings:
            raise OSError("parent fsync failed")

    first = LocalRecordingCommitter(
        MeetingStore(meetings, directory_sync=fail_parent_sync),
        events.append,
        converter=lambda *_args: (_ for _ in ()).throw(AssertionError("no WAV")),
        validate_m4a=lambda _path: None,
    )
    assert first.commit(entry, entry.meta) is None
    assert isinstance(events[0], RecordingPublicationUncertain)

    launches: list[object] = []
    retry = LocalRecordingCommitter(
        MeetingStore(meetings),
        events.append,
        converter=lambda *_args: (_ for _ in ()).throw(AssertionError("converted twice")),
        validate_m4a=lambda *_args: (_ for _ in ()).throw(AssertionError("validated twice")),
        post_commit_launcher=lambda files, policy: launches.append((files, policy)),
    )
    files = retry.commit(entry, entry.meta)

    assert files is not None and files.directory == meetings / entry.meta.slug
    assert not source.exists()
    assert len(launches) == 1
    assert not (meetings / f"{entry.meta.slug}-2").exists()


@pytest.mark.parametrize("origin", ["indexed", "legacy"])
@pytest.mark.parametrize("mutation", ["replace", "same-inode"])
def test_commit_preserves_sealed_source_provenance(
    tmp_path: Path,
    origin: str,
    mutation: str,
) -> None:
    if origin == "indexed":
        entry, meta = _entry(tmp_path)
    else:
        legacy = tmp_path / "legacy"
        legacy.mkdir()
        source = legacy / "meeting-memory-2026-08-10_10-00_legacy.m4a"
        source.write_bytes(b"legacy-audio")
        entry = discover_legacy_once(legacy, LegacyDiscoveryState()).entries[0]
        meta = entry.meta
    source = entry.source_path
    original = source.read_bytes()
    changed = bytes([original[0] ^ 1]) + original[1:]
    if mutation == "replace":
        source.rename(source.with_name(f"{source.name}.original"))
        source.write_bytes(original)
    else:
        source.write_bytes(changed)
    committer = LocalRecordingCommitter(
        MeetingStore(tmp_path / f"meetings-{origin}-{mutation}"),
        lambda _event: None,
        converter=lambda wav, output: output.write_bytes(wav.read_bytes()),
        validate_m4a=lambda _path: None,
    )

    with pytest.raises(ValueError, match="source changed before commit"):
        committer.commit(entry, meta)


def test_partially_pinned_source_is_rejected_without_repin(tmp_path: Path) -> None:
    entry, meta = _entry(tmp_path)
    partial = replace(entry, source_sha256=None)
    committer = LocalRecordingCommitter(
        MeetingStore(tmp_path / "meetings-partial"),
        lambda _event: None,
        converter=lambda _wav, output: output.write_bytes(b"m4a"),
        validate_m4a=lambda _path: None,
    )

    with pytest.raises(ValueError, match="provenance is incomplete"):
        committer.commit(partial, meta)


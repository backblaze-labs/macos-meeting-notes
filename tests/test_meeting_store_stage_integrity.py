"""Adversarial stage and publication identity tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from meeting_memory.service.local_commit import LocalRecordingCommitter
from meeting_memory.service.meeting_store import (
    MeetingPublicationIntegrityError,
    MeetingStore,
)
from meeting_memory.service.recovery_commit import RecoveryPublicationRejected
from meeting_memory.service.recovery_index import create_recovery_session, pin_recovery_source
from meeting_memory.types.meeting import MeetingMeta


@pytest.mark.parametrize("swap", ["stage", "audio"])
def test_validator_path_swap_preserves_recovery_without_event_or_workers(
    tmp_path: Path,
    swap: str,
) -> None:
    entry, meta = _recovery(tmp_path)
    events: list[object] = []
    workers: list[object] = []
    materialized: list[Path] = []

    def converter(_wav: Path, output: Path) -> None:
        materialized.append(output)
        output.write_bytes(b"VALID")

    def validator(snapshot: Path) -> None:
        assert snapshot.read_bytes() == b"VALID"
        output = materialized[0]
        if swap == "stage":
            accepted = output.parent.with_name(f"{output.parent.name}.accepted")
            output.parent.rename(accepted)
            output.parent.mkdir()
            output.write_bytes(b"INVALID")
        else:
            output.rename(output.with_name("accepted.m4a"))
            output.write_bytes(b"INVALID")

    committer = LocalRecordingCommitter(
        MeetingStore(tmp_path / "meetings"),
        events.append,
        converter=converter,
        validate_m4a=validator,
        post_commit_launcher=lambda files, policy: workers.append((files, policy)),
    )

    with pytest.raises((OSError, RuntimeError, ValueError)):
        committer.commit(entry, meta)

    assert entry.source_path.read_bytes().endswith(b"samples")
    assert not (tmp_path / "meetings" / meta.slug).exists()
    assert events == []
    assert workers == []


def test_validator_cannot_accept_transient_materialized_bytes(
    tmp_path: Path,
) -> None:
    entry, meta = _recovery(tmp_path)
    events: list[object] = []
    materialized: list[Path] = []

    def convert(_wav: Path, output: Path) -> None:
        materialized.append(output)
        output.write_bytes(b"BAD")

    def validator(snapshot: Path) -> None:
        output = materialized[0]
        output.write_bytes(b"GOOD")
        try:
            if snapshot.read_bytes() != b"GOOD":
                raise ValueError("validator did not receive transient GOOD bytes")
        finally:
            output.write_bytes(b"BAD")

    committer = LocalRecordingCommitter(
        MeetingStore(tmp_path / "meetings-transient"),
        events.append,
        converter=convert,
        validate_m4a=validator,
    )

    with pytest.raises(ValueError, match="transient GOOD"):
        committer.commit(entry, meta)

    assert entry.source_path.exists()
    assert events == []
    assert not (tmp_path / "meetings-transient" / meta.slug).exists()


@pytest.mark.parametrize("swap", ["directory", "audio"])
def test_postpublish_identity_check_rejects_replacement(
    tmp_path: Path,
    swap: str,
) -> None:
    source = tmp_path / "source.m4a"
    source.write_bytes(b"VALID")
    meetings = tmp_path / "meetings"

    def publisher(stage: Path, destination: Path) -> None:
        if swap == "directory":
            accepted = stage.with_name(f"{stage.name}.accepted")
            stage.rename(accepted)
            stage.mkdir()
            (stage / "recording.m4a").write_bytes(b"VALID")
            (stage / "transcript.md").write_text("replacement", encoding="utf-8")
            stage.rename(destination)
        else:
            stage.rename(destination)
            audio = destination / "recording.m4a"
            audio.rename(destination / "accepted.m4a")
            audio.write_bytes(b"VALID")

    with pytest.raises(MeetingPublicationIntegrityError):
        MeetingStore(meetings, publisher=publisher).commit(source, _meta())

    assert source.read_bytes() == b"VALID"


def test_postpublish_audio_swap_never_cleans_or_launches_recovery(
    tmp_path: Path,
) -> None:
    entry, meta = _recovery(tmp_path)
    events: list[object] = []
    workers: list[object] = []
    meetings = tmp_path / "meetings-recovery"

    def publisher(stage: Path, destination: Path) -> None:
        stage.rename(destination)
        audio = destination / "recording.m4a"
        audio.rename(destination / "accepted.m4a")
        audio.write_bytes(b"INVALID")

    committer = LocalRecordingCommitter(
        MeetingStore(meetings, publisher=publisher),
        events.append,
        converter=lambda _wav, output: output.write_bytes(b"VALID"),
        validate_m4a=lambda path: path.read_bytes() == b"VALID",
        post_commit_launcher=lambda files, policy: workers.append((files, policy)),
    )

    with pytest.raises(RecoveryPublicationRejected) as caught:
        committer.commit(entry, meta)

    assert caught.value.quarantine_error is None
    assert entry.source_path.exists()
    assert events == []
    assert workers == []
    assert not (meetings / meta.slug).exists()
    assert not (meetings / f"{meta.slug}-2").exists()

    retry = LocalRecordingCommitter(
        MeetingStore(meetings),
        events.append,
        converter=lambda _wav, output: output.write_bytes(b"VALID"),
        validate_m4a=_require_valid,
        post_commit_launcher=lambda files, policy: workers.append((files, policy)),
    )
    files = retry.commit(entry, meta)

    assert files is not None
    assert files.meta.slug == meta.slug
    assert not entry.source_path.exists()
    assert len(events) == 1
    assert len(workers) == 1
    assert not (meetings / f"{meta.slug}-2").exists()


def test_rejected_unrelated_publication_is_preserved_and_retry_uses_suffix(
    tmp_path: Path,
) -> None:
    entry, meta = _recovery(tmp_path)
    events: list[object] = []
    workers: list[object] = []
    meetings = tmp_path / "meetings-unrelated"

    def publisher(stage: Path, destination: Path) -> None:
        stage.rename(stage.with_name(f"{stage.name}.accepted"))
        stage.mkdir()
        (stage / "recording.m4a").write_bytes(b"UNRELATED")
        (stage / "transcript.md").write_text("unrelated", encoding="utf-8")
        stage.rename(destination)

    first = LocalRecordingCommitter(
        MeetingStore(meetings, publisher=publisher),
        events.append,
        converter=lambda _wav, output: output.write_bytes(b"VALID"),
        validate_m4a=_require_valid,
        post_commit_launcher=lambda files, policy: workers.append((files, policy)),
    )
    with pytest.raises(RecoveryPublicationRejected) as caught:
        first.commit(entry, meta)

    assert caught.value.quarantine_error is not None
    assert (meetings / meta.slug / "recording.m4a").read_bytes() == b"UNRELATED"
    assert entry.source_path.exists()
    assert events == []
    assert workers == []

    retry = LocalRecordingCommitter(
        MeetingStore(meetings),
        events.append,
        converter=lambda _wav, output: output.write_bytes(b"VALID"),
        validate_m4a=_require_valid,
        post_commit_launcher=lambda files, policy: workers.append((files, policy)),
    )
    files = retry.commit(entry, meta)

    assert files is not None
    assert files.meta.slug == f"{meta.slug}-2"
    assert (meetings / meta.slug / "recording.m4a").read_bytes() == b"UNRELATED"
    assert len(events) == 1
    assert len(workers) == 1


def _require_valid(path: Path) -> None:
    if path.read_bytes() != b"VALID":
        raise ValueError("invalid test M4A")


def _recovery(tmp_path: Path):
    meta = _meta()
    entry = create_recovery_session(tmp_path / "capture", meta)
    entry.source_path.write_bytes(b"RIFF\x00\x00\x00\x00WAVEsamples")
    return pin_recovery_source(entry), meta


def _meta() -> MeetingMeta:
    return MeetingMeta(
        "2026-08-10_10-00_stage-swap",
        datetime(2026, 8, 10, 10, tzinfo=UTC),
        "Stage Swap",
    )

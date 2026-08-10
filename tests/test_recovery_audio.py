"""Adversarial tests for recovery audio materialization."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from meeting_memory.service.meeting_store import MeetingStore
from meeting_memory.service.recovery_cleanup import cleanup_recovery_after_commit
from meeting_memory.service.recovery_commit import commit_recovery
from meeting_memory.service.recovery_index import (
    create_recovery_session,
    pin_recovery_source,
)
from meeting_memory.types.meeting import MeetingMeta


def test_wav_recovery_requires_conversion_and_never_copies_riff_as_m4a(
    tmp_path: Path,
) -> None:
    entry = _pinned_wav_entry(tmp_path / "staging", b"pcm")

    with pytest.raises(ValueError, match="requires an audio converter"):
        commit_recovery(
            MeetingStore(tmp_path / "meetings"),
            entry,
            validate_m4a=_validate_aac,
        )

    assert entry.source_path.read_bytes().startswith(b"RIFF")
    assert entry.index_path is not None and entry.index_path.exists()
    assert not (tmp_path / "meetings" / entry.meta.slug).exists()


@pytest.mark.parametrize(
    "invalid",
    [
        b"\x00\x00\x00\x10ftypM4A \x00\x00\x00\x00",
        b"TEST-M4A\0",
        b"TEST-M4A\0PCM\0samples",
    ],
    ids=["ftyp-only", "truncated", "no-aac"],
)
def test_direct_recovery_requires_caller_validated_complete_aac_m4a(
    tmp_path: Path,
    invalid: bytes,
) -> None:
    entry = create_recovery_session(tmp_path / "staging", _meta())
    source = entry.source_path.with_suffix(".m4a")
    entry = replace(entry, source_path=source)
    source.write_bytes(invalid)
    entry = pin_recovery_source(entry)

    with pytest.raises(ValueError, match="complete AAC M4A"):
        commit_recovery(
            MeetingStore(tmp_path / "meetings"),
            entry,
            validate_m4a=_validate_aac,
        )

    assert entry.source_path.read_bytes() == invalid
    assert entry.index_path is not None and entry.index_path.exists()
    assert not (tmp_path / "meetings" / entry.meta.slug).exists()


@pytest.mark.parametrize("failure", ["raise", "invalid-output"])
def test_wav_conversion_failure_preserves_source_and_has_zero_final(
    tmp_path: Path,
    failure: str,
) -> None:
    entry = _pinned_wav_entry(tmp_path / "staging", b"pcm")

    def converter(source: Path, destination: Path) -> None:
        assert source != entry.source_path
        assert source.read_bytes() == entry.source_path.read_bytes()
        if failure == "raise":
            raise RuntimeError("conversion failed")
        destination.write_bytes(b"RIFF-invalid-output")

    with pytest.raises((RuntimeError, ValueError)):
        commit_recovery(
            MeetingStore(tmp_path / "meetings"),
            entry,
            converter=converter,
            validate_m4a=_validate_aac,
        )

    assert entry.source_path.exists()
    assert entry.index_path is not None and entry.index_path.exists()
    assert not (tmp_path / "meetings" / entry.meta.slug).exists()


def test_wav_conversion_uses_private_stable_path_and_publishes_valid_m4a(
    tmp_path: Path,
) -> None:
    entry = _pinned_wav_entry(tmp_path / "staging", b"pcm")
    observed: list[Path] = []

    def converter(source: Path, destination: Path) -> None:
        observed.append(source)
        assert source != entry.source_path
        assert source.read_bytes().startswith(b"RIFF")
        destination.write_bytes(_m4a(b"converted"))

    result = commit_recovery(
        MeetingStore(tmp_path / "meetings"),
        entry,
        converter=converter,
        validate_m4a=_validate_aac,
    )

    assert len(observed) == 1
    assert not observed[0].exists()
    assert result.files.audio_path.read_bytes() == _m4a(b"converted")
    assert not result.files.audio_path.read_bytes().startswith(b"RIFF")
    assert entry.source_path.exists()
    cleanup_recovery_after_commit(result.receipt)


def test_exact_m4a_copy_detects_mutate_then_restore_race_before_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = _pinned_m4a_entry(tmp_path / "staging", b"source-a")
    original = entry.source_path.read_bytes()
    replacement = _m4a(b"source-b")
    assert len(replacement) == len(original)
    from meeting_memory.service import recovery_audio

    real_copy = recovery_audio.copy_audio_from_fd
    mutated = False

    def mutate_during_copy(descriptor: int, destination: Path) -> None:
        nonlocal mutated
        mutated = True
        entry.source_path.write_bytes(replacement)
        try:
            real_copy(descriptor, destination)
        finally:
            entry.source_path.write_bytes(original)

    monkeypatch.setattr(recovery_audio, "copy_audio_from_fd", mutate_during_copy)

    with pytest.raises(ValueError, match="does not match"):
        commit_recovery(
            MeetingStore(tmp_path / "meetings"),
            entry,
            validate_m4a=_validate_aac,
        )

    assert mutated
    assert entry.source_path.read_bytes() == original
    assert entry.index_path is not None and entry.index_path.exists()
    assert not (tmp_path / "meetings" / entry.meta.slug).exists()


def test_wav_snapshot_cleanup_failure_happens_before_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = _pinned_wav_entry(tmp_path / "staging", b"pcm")
    from meeting_memory.service import recovery_audio

    def converter(_source: Path, destination: Path) -> None:
        destination.write_bytes(_m4a(b"converted"))

    def fail_cleanup(_snapshot) -> None:
        raise OSError("injected conversion snapshot cleanup failure")

    monkeypatch.setattr(recovery_audio._StableSnapshot, "cleanup", fail_cleanup)

    with pytest.raises(OSError, match="snapshot cleanup failure"):
        commit_recovery(
            MeetingStore(tmp_path / "meetings"),
            entry,
            converter=converter,
            validate_m4a=_validate_aac,
        )

    assert entry.source_path.exists()
    assert entry.index_path is not None and entry.index_path.exists()
    assert not (tmp_path / "meetings" / entry.meta.slug).exists()


def _meta() -> MeetingMeta:
    return MeetingMeta(
        "2026-08-10_10-00_atomic", datetime(2026, 8, 10, 10, tzinfo=UTC), "Atomic", 2
    )


def _pinned_m4a_entry(root: Path, content: bytes):
    entry = create_recovery_session(root, _meta())
    source = entry.source_path.with_suffix(".m4a")
    source.write_bytes(_m4a(content))
    return pin_recovery_source(replace(entry, source_path=source))


def _pinned_wav_entry(root: Path, content: bytes):
    entry = create_recovery_session(root, _meta())
    entry.source_path.write_bytes(_wav(content))
    return pin_recovery_source(entry)


def _m4a(content: bytes) -> bytes:
    return b"TEST-M4A\0AAC\0" + content


def _wav(content: bytes) -> bytes:
    return b"RIFF" + len(content).to_bytes(4, "little") + b"WAVE" + content


def _validate_aac(path: Path) -> None:
    content = path.read_bytes()
    if not content.startswith(b"TEST-M4A\0AAC\0") or len(content) <= 13:
        raise ValueError("test validator requires a complete AAC M4A")

"""Explicit once-only legacy recovery discovery tests."""

from __future__ import annotations

import os
import tempfile
import wave
from pathlib import Path

import pytest

from meeting_memory.service.legacy_recovery_index import (
    LEGACY_MARKER_FILENAME,
    discover_legacy_once,
    load_legacy_discovery_state,
    persist_legacy_discovery_complete,
)
from meeting_memory.types.recovery import LegacyDiscoveryState


def test_legacy_scan_prefers_valid_m4a_and_falls_back_from_invalid_m4a(
    tmp_path: Path,
) -> None:
    preferred = "meeting-memory-2026-08-10_10-00_preferred"
    fallback = "meeting-memory-2026-08-10_10-01_fallback"
    _write_wav(tmp_path / f"{preferred}.wav")
    (tmp_path / f"{preferred}.m4a").write_bytes(b"ready")
    _write_wav(tmp_path / f"{fallback}.wav")
    secret = tmp_path / "secret"
    secret.write_bytes(b"private")
    (tmp_path / f"{fallback}.m4a").symlink_to(secret)

    result = discover_legacy_once(tmp_path, LegacyDiscoveryState())

    assert [entry.source_path.suffix for entry in result.entries] == [".m4a", ".wav"]
    assert result.state.completed
    assert secret.read_bytes() == b"private"


def test_completed_state_does_zero_directory_iteration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(_descriptor: int) -> list[str]:
        raise AssertionError("completed discovery must not enumerate")

    monkeypatch.setattr(os, "listdir", explode)
    state = LegacyDiscoveryState(completed=True)
    result = discover_legacy_once(tmp_path, state)
    assert result.entries == ()
    assert result.state is state


def test_durable_marker_round_trip_and_filename_validation(tmp_path: Path) -> None:
    marker = tmp_path / "private" / LEGACY_MARKER_FILENAME
    assert not load_legacy_discovery_state(marker).completed
    assert persist_legacy_discovery_complete(marker).completed
    assert load_legacy_discovery_state(marker).completed

    invalid_parent = tmp_path / "invalid"
    with pytest.raises(ValueError, match="must be named"):
        persist_legacy_discovery_complete(invalid_parent / "wrong.json")
    assert not invalid_parent.exists()


def test_marker_rejects_intermediate_symlink_without_outside_writes(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "link"
    link.symlink_to(outside, target_is_directory=True)

    with pytest.raises(OSError):
        persist_legacy_discovery_complete(link / LEGACY_MARKER_FILENAME)
    assert not any(outside.iterdir())


def test_legacy_scan_trusts_only_root_symlink_and_returns_canonical_paths(
    tmp_path: Path,
) -> None:
    canonical = tmp_path / "canonical-temp"
    canonical.mkdir()
    source = canonical / "meeting-memory-2026-08-10_10-04_alias.wav"
    _write_wav(source)
    secret = canonical / "private"
    secret.write_bytes(b"secret")
    candidate_link = canonical / "meeting-memory-2026-08-10_10-05_link.m4a"
    candidate_link.symlink_to(secret)
    configured = tmp_path / "configured-temp"
    configured.symlink_to(canonical, target_is_directory=True)

    result = discover_legacy_once(configured, LegacyDiscoveryState())

    assert [entry.source_path for entry in result.entries] == [source]
    assert result.entries[0].session_directory == canonical.resolve()
    assert secret.read_bytes() == b"secret"


def test_macos_temp_root_is_canonicalized_before_nofollow_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[int] = []

    def empty_scan(descriptor: int) -> list[str]:
        observed.append(descriptor)
        return []

    monkeypatch.setattr(os, "listdir", empty_scan)
    result = discover_legacy_once(
        Path(tempfile.gettempdir()),
        LegacyDiscoveryState(),
    )

    assert observed
    assert result.entries == ()
    assert result.state.completed


def test_failed_enumeration_does_not_consume_the_once_only_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "meeting-memory-2026-08-10_10-03_retry.wav"
    _write_wav(source)
    state = LegacyDiscoveryState()
    real_listdir = os.listdir
    attempts = 0

    def fail_once(path) -> list[str]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError("temporarily unreadable")
        return real_listdir(path)

    monkeypatch.setattr(os, "listdir", fail_once)
    with pytest.raises(PermissionError, match="temporarily unreadable"):
        discover_legacy_once(tmp_path, state)

    result = discover_legacy_once(tmp_path, state)
    assert not state.completed
    assert [entry.source_path for entry in result.entries] == [source]
    assert result.state.completed


def _write_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8_000)
        audio.writeframes(b"\0\0" * 8_000)

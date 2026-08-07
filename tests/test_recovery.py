"""Tests for interrupted recording recovery."""

from __future__ import annotations

import wave
from datetime import UTC, datetime
from pathlib import Path

import pytest

from meeting_memory.service.recovery import (
    clear_audio_recovery_marker,
    convert_recovered_recording,
    find_recovered_recordings,
    mark_audio_for_recovery,
)
from meeting_memory.types.meeting import MeetingMeta


def test_find_recovered_recordings_ignores_completed_conversions(tmp_path: Path) -> None:
    recovered_wav = tmp_path / "meeting-memory-2026-06-11_09-00_product-sync.wav"
    completed_wav = tmp_path / "meeting-memory-2026-06-11_10-00_done.wav"
    _write_wav(recovered_wav, frames=16_000 * 120)
    _write_wav(completed_wav, frames=16_000)
    completed_wav.with_suffix(".m4a").write_bytes(b"audio")

    recordings = find_recovered_recordings(tmp_path)

    assert len(recordings) == 1
    assert recordings[0].wav_path == recovered_wav
    assert recordings[0].meta.slug == "2026-06-11_09-00_product-sync"
    assert recordings[0].meta.calendar_title == "Product Sync"
    assert recordings[0].meta.duration_minutes == 2
    assert isinstance(recordings[0].meta.started_at, datetime)


def test_convert_recovered_recording_removes_wav_after_conversion(tmp_path: Path) -> None:
    wav_path = tmp_path / "meeting-memory-2026-06-11_09-00_product-sync.wav"
    _write_wav(wav_path, frames=16_000)
    recording = find_recovered_recordings(tmp_path)[0]

    audio_path = convert_recovered_recording(
        recording,
        converter=lambda wav, m4a: m4a.write_bytes(wav.read_bytes()),
    )

    assert audio_path == wav_path.with_suffix(".m4a")
    assert audio_path.exists()
    assert not wav_path.exists()


def test_find_recovered_recordings_ignores_header_only_wav(tmp_path: Path) -> None:
    header_only = tmp_path / "meeting-memory-2026-06-11_09-00_empty.wav"
    _write_wav(header_only, frames=0)

    assert header_only.stat().st_size == 44
    assert find_recovered_recordings(tmp_path) == []


def test_pending_m4a_marker_is_recoverable_without_reconversion(tmp_path: Path) -> None:
    audio_path = tmp_path / "meeting-memory-2026-06-11_09-00_product-sync.m4a"
    audio_path.write_bytes(b"converted audio")
    meta = MeetingMeta(
        slug="2026-06-11_09-00_product-sync",
        started_at=datetime(2026, 6, 11, 9, 0, tzinfo=UTC),
        calendar_title="Product Sync",
        duration_minutes=2,
        speaker_candidates=("Alex",),
    )
    marker = mark_audio_for_recovery(audio_path, meta)

    recording = find_recovered_recordings(tmp_path)[0]

    assert recording.audio_path == audio_path
    assert recording.meta == meta
    assert convert_recovered_recording(recording) == audio_path
    assert audio_path.exists()
    assert marker.exists()
    clear_audio_recovery_marker(audio_path)
    assert not marker.exists()


def test_marker_failure_rolls_back_m4a_and_preserves_recoverable_wav(
    tmp_path: Path,
) -> None:
    wav_path = tmp_path / "meeting-memory-2026-06-11_09-00_product-sync.wav"
    _write_wav(wav_path, frames=16_000)
    recording = find_recovered_recordings(tmp_path)[0]

    def fail_marker(_audio: Path, _meta: MeetingMeta) -> Path:
        raise OSError("disk full")

    with pytest.raises(OSError, match="disk full"):
        convert_recovered_recording(
            recording,
            converter=lambda wav, m4a: m4a.write_bytes(wav.read_bytes()),
            marker_writer=fail_marker,
        )

    assert wav_path.exists()
    assert not wav_path.with_suffix(".m4a").exists()
    assert find_recovered_recordings(tmp_path)[0].wav_path == wav_path


def _write_wav(path: Path, *, frames: int) -> None:
    with wave.open(str(path), "wb") as audio_file:
        audio_file.setnchannels(1)
        audio_file.setsampwidth(2)
        audio_file.setframerate(16_000)
        audio_file.writeframes(b"\0\0" * frames)

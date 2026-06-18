"""Tests for interrupted recording recovery."""

from __future__ import annotations

import wave
from datetime import datetime
from pathlib import Path

from meeting_memory.service.recovery import (
    convert_recovered_recording,
    find_recovered_recordings,
)


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


def _write_wav(path: Path, *, frames: int) -> None:
    with wave.open(str(path), "wb") as audio_file:
        audio_file.setnchannels(1)
        audio_file.setsampwidth(2)
        audio_file.setframerate(16_000)
        audio_file.writeframes(b"\0\0" * frames)

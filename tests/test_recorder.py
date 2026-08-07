"""Tests for the recorder service."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from meeting_memory.service.recorder import RecorderService


def test_recorder_start_stop_uses_native_capture_and_converts_to_m4a(
    tmp_path: Path,
) -> None:
    times = iter(
        [
            datetime(2026, 6, 11, 9, 0, tzinfo=UTC),
            datetime(2026, 6, 11, 9, 3, tzinfo=UTC),
        ]
    )
    captures: list[FakeCapture] = []
    converted: list[tuple[Path, Path]] = []

    def start_capture(mode: str, path: Path) -> FakeCapture:
        capture = FakeCapture(mode, path)
        capture.write_audio()
        captures.append(capture)
        return capture

    recorder = RecorderService(
        capture_mode="full-meeting",
        temp_dir=tmp_path,
        now=lambda: next(times),
        capture_starter=start_capture,
        converter=lambda wav, m4a: _copy_conversion(wav, m4a, converted),
    )

    session = recorder.start("Product Sync")
    assert session is not None
    assert recorder.start("Ignored") is None

    result = recorder.stop()

    assert result is not None
    assert recorder.is_recording is False
    assert result.meta.slug == "2026-06-11_09-00_product-sync"
    assert result.meta.duration_minutes == 3
    assert result.audio_path.suffix == ".m4a"
    assert result.audio_path.exists()
    assert not result.wav_path.exists()
    assert converted == [(result.wav_path, result.audio_path)]
    assert captures[0].mode == "full-meeting"
    assert captures[0].stopped is True


def test_recorder_passes_silent_mode_to_native_capture(tmp_path: Path) -> None:
    modes: list[str] = []

    def start_capture(mode: str, path: Path) -> FakeCapture:
        modes.append(mode)
        capture = FakeCapture(mode, path)
        capture.write_audio()
        return capture

    recorder = RecorderService(
        capture_mode="silent-system-only",
        temp_dir=tmp_path,
        capture_starter=start_capture,
        converter=lambda wav, m4a: m4a.write_bytes(wav.read_bytes()),
    )

    recorder.start("Quiet Review")
    recorder.stop()

    assert modes == ["silent-system-only"]


def test_recorder_stop_without_session_is_noop(tmp_path: Path) -> None:
    recorder = RecorderService(temp_dir=tmp_path)

    assert recorder.stop() is None


def test_recorder_start_failure_cleans_partial_state(tmp_path: Path) -> None:
    calls = 0

    def start_capture(mode: str, path: Path) -> FakeCapture:
        nonlocal calls
        calls += 1
        if calls == 1:
            path.write_bytes(b"partial")
            raise RuntimeError("native capture unavailable")
        capture = FakeCapture(mode, path)
        capture.write_audio()
        return capture

    recorder = RecorderService(
        temp_dir=tmp_path,
        now=lambda: datetime(2026, 6, 11, 9, 0, tzinfo=UTC),
        capture_starter=start_capture,
        converter=lambda wav, m4a: m4a.write_bytes(wav.read_bytes()),
    )

    with pytest.raises(RuntimeError, match="native capture unavailable"):
        recorder.start("Product Sync")

    assert recorder.is_recording is False
    assert recorder.active_session is None
    assert list(tmp_path.glob("*.wav")) == []

    assert recorder.start("Product Sync") is not None
    assert recorder.is_recording is True


class FakeCapture:
    def __init__(self, mode: str, output_path: Path):
        self.mode = mode
        self.output_path = output_path
        self.stopped = False

    def write_audio(self) -> None:
        self.output_path.write_bytes(b"RIFF" + b"\0" * 64)

    def stop(self) -> Path:
        self.stopped = True
        return self.output_path


def _copy_conversion(
    wav_path: Path,
    m4a_path: Path,
    converted: list[tuple[Path, Path]],
) -> None:
    converted.append((wav_path, m4a_path))
    m4a_path.write_bytes(wav_path.read_bytes())

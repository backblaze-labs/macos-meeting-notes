"""Tests for the recorder service."""

from __future__ import annotations

import threading
import time
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


def test_recorder_health_failure_clears_active_state_and_preserves_wav(tmp_path: Path) -> None:
    captures: list[FailingHealthCapture] = []

    def start_capture(mode: str, path: Path) -> FailingHealthCapture:
        capture = FailingHealthCapture(mode, path)
        capture.write_audio()
        captures.append(capture)
        return capture

    recorder = RecorderService(
        temp_dir=tmp_path,
        capture_starter=start_capture,
    )
    recorder.start("Product Sync")

    with pytest.raises(RuntimeError, match="device disconnected"):
        recorder.check_health()

    assert recorder.is_recording is False
    assert recorder.active_session is None
    assert captures[0].output_path.exists()


def test_recorder_serializes_health_check_and_stop(tmp_path: Path) -> None:
    captures: list[InterleavedCapture] = []

    def start_capture(mode: str, path: Path) -> InterleavedCapture:
        capture = InterleavedCapture(mode, path)
        capture.write_audio()
        captures.append(capture)
        return capture

    recorder = RecorderService(
        temp_dir=tmp_path,
        capture_starter=start_capture,
        converter=lambda wav, m4a: m4a.write_bytes(wav.read_bytes()),
    )
    recorder.start("Product Sync")
    errors: list[Exception] = []
    results = []
    stop_attempted = threading.Event()

    def stop_recording() -> None:
        stop_attempted.set()
        results.append(recorder.stop())

    health_thread = threading.Thread(target=lambda: _capture_errors(recorder.check_health, errors))
    health_thread.start()
    assert captures[0].health_entered.wait(timeout=1)

    stop_thread = threading.Thread(target=stop_recording)
    stop_thread.start()
    assert stop_attempted.wait(timeout=1)
    assert captures[0].stop_entered.wait(timeout=0.05) is False

    captures[0].release_health.set()
    health_thread.join(timeout=1)
    stop_thread.join(timeout=1)

    assert health_thread.is_alive() is False
    assert stop_thread.is_alive() is False
    assert errors == []
    assert captures[0].stop_entered.is_set()
    assert len(results) == 1


def test_recorder_suppresses_health_error_when_stop_wins(tmp_path: Path) -> None:
    captures: list[InterleavedCapture] = []

    def start_capture(mode: str, path: Path) -> InterleavedCapture:
        capture = InterleavedCapture(mode, path, health_error=RuntimeError("late poll"))
        capture.write_audio()
        captures.append(capture)
        return capture

    recorder = RecorderService(
        temp_dir=tmp_path,
        capture_starter=start_capture,
        converter=lambda wav, m4a: m4a.write_bytes(wav.read_bytes()),
    )
    recorder.start("Product Sync")
    health_errors: list[Exception] = []
    stop_errors: list[Exception] = []
    health_thread = threading.Thread(
        target=lambda: _capture_errors(recorder.check_health, health_errors)
    )
    health_thread.start()
    assert captures[0].health_entered.wait(timeout=1)

    stop_thread = threading.Thread(target=lambda: _capture_errors(recorder.stop, stop_errors))
    stop_thread.start()
    deadline = time.monotonic() + 1
    while not recorder.is_stopping and time.monotonic() < deadline:
        time.sleep(0.001)
    assert recorder.is_stopping is True

    captures[0].release_health.set()
    health_thread.join(timeout=1)
    stop_thread.join(timeout=1)

    assert health_errors == []
    assert stop_errors == []
    assert recorder.is_recording is False
    assert recorder.is_stopping is False


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


class FailingHealthCapture(FakeCapture):
    def check_health(self) -> None:
        raise RuntimeError("device disconnected")


class InterleavedCapture(FakeCapture):
    def __init__(
        self,
        mode: str,
        output_path: Path,
        health_error: Exception | None = None,
    ):
        super().__init__(mode, output_path)
        self.health_error = health_error
        self.health_entered = threading.Event()
        self.release_health = threading.Event()
        self.stop_entered = threading.Event()

    def check_health(self) -> None:
        self.health_entered.set()
        if not self.release_health.wait(timeout=1):
            raise TimeoutError("test did not release health check")
        if self.health_error is not None:
            raise self.health_error

    def stop(self) -> Path:
        self.stop_entered.set()
        return super().stop()


def _capture_errors(callback, errors: list[Exception]) -> None:
    try:
        callback()
    except Exception as exc:
        errors.append(exc)


def _copy_conversion(
    wav_path: Path,
    m4a_path: Path,
    converted: list[tuple[Path, Path]],
) -> None:
    converted.append((wav_path, m4a_path))
    m4a_path.write_bytes(wav_path.read_bytes())

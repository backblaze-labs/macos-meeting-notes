"""Concurrency tests for the recorder lifecycle."""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from meeting_memory.service.recorder import RecorderService


def test_start_is_rejected_until_stop_and_conversion_finish(tmp_path: Path) -> None:
    fixed_now = datetime(2026, 6, 11, 9, 0, tzinfo=UTC)
    captures: list[BlockingStopCapture] = []
    stop_release = threading.Event()
    conversion_entered = threading.Event()
    conversion_release = threading.Event()

    def start_capture(mode: str, path: Path) -> BlockingStopCapture:
        capture = BlockingStopCapture(mode, path, stop_release, len(captures) + 1)
        capture.write_audio()
        captures.append(capture)
        return capture

    def convert(wav_path: Path, m4a_path: Path) -> None:
        conversion_entered.set()
        if not conversion_release.wait(timeout=2):
            raise TimeoutError("test did not release conversion")
        m4a_path.write_bytes(wav_path.read_bytes())

    recorder = RecorderService(
        temp_dir=tmp_path,
        now=lambda: fixed_now,
        capture_starter=start_capture,
        converter=convert,
    )
    first_session = recorder.start("Product Sync")
    assert first_session is not None
    stop_results = []
    stop_errors: list[Exception] = []
    stop_thread = threading.Thread(
        target=lambda: _capture_result(recorder.stop, stop_results, stop_errors),
        daemon=True,
    )
    stop_thread.start()

    try:
        assert captures[0].stop_entered.wait(timeout=1)
        assert recorder.is_recording is True
        assert recorder.is_stopping is True

        started_at = time.monotonic()
        assert recorder.start("Product Sync") is None
        assert time.monotonic() - started_at < 0.3
        assert len(captures) == 1
        assert first_session.wav_path.read_bytes() == b"capture-1"

        stop_release.set()
        assert conversion_entered.wait(timeout=1)

        assert recorder.start("Product Sync") is None
        assert len(captures) == 1
        assert recorder.is_recording is True
        assert recorder.is_stopping is True

        conversion_release.set()
        stop_thread.join(timeout=1)
        assert stop_thread.is_alive() is False
        assert stop_errors == []
        assert len(stop_results) == 1
        assert recorder.is_recording is False
        assert recorder.is_stopping is False

        m4a_path = first_session.wav_path.with_suffix(".m4a")
        assert m4a_path.read_bytes() == b"capture-1"
        assert not first_session.wav_path.exists()

        second_session = recorder.start("Product Sync")
        assert second_session is not None
        assert second_session.wav_path != first_session.wav_path
        assert second_session.wav_path.parent != first_session.wav_path.parent
        assert len(captures) == 2
        assert second_session.wav_path.read_bytes() == b"capture-2"
        assert m4a_path.read_bytes() == b"capture-1"
    finally:
        stop_release.set()
        conversion_release.set()
        stop_thread.join(timeout=1)


def test_stop_failure_releases_lifecycle_for_next_start(tmp_path: Path) -> None:
    def start_capture(_mode: str, path: Path) -> ImmediateCapture:
        path.write_bytes(b"audio")
        return ImmediateCapture(path)

    def fail_conversion(_wav_path: Path, _m4a_path: Path) -> None:
        raise RuntimeError("conversion failed")

    recorder = RecorderService(
        temp_dir=tmp_path,
        now=lambda: datetime(2026, 6, 11, 9, 0, tzinfo=UTC),
        capture_starter=start_capture,
        converter=fail_conversion,
    )
    recorder.start("Product Sync")

    with pytest.raises(RuntimeError, match="conversion failed"):
        recorder.stop()

    assert recorder.is_recording is False
    assert recorder.is_stopping is False
    assert recorder.start("Product Sync") is not None


class BlockingStopCapture:
    def __init__(
        self,
        mode: str,
        output_path: Path,
        stop_release: threading.Event,
        sequence: int,
    ) -> None:
        self.mode = mode
        self.output_path = output_path
        self.stop_release = stop_release
        self.sequence = sequence
        self.stop_entered = threading.Event()

    def write_audio(self) -> None:
        self.output_path.write_bytes(f"capture-{self.sequence}".encode())

    def stop(self) -> Path:
        self.stop_entered.set()
        if not self.stop_release.wait(timeout=2):
            raise TimeoutError("test did not release stop")
        return self.output_path


class ImmediateCapture:
    def __init__(self, output_path: Path) -> None:
        self.output_path = output_path

    def stop(self) -> Path:
        return self.output_path


def _capture_result(callback, results: list, errors: list[Exception]) -> None:
    try:
        results.append(callback())
    except Exception as exc:
        errors.append(exc)

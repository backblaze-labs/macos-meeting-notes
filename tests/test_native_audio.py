"""Tests for the native macOS audio helper adapter."""

from __future__ import annotations

import io
import subprocess
import threading
from pathlib import Path

import pytest

from meeting_memory.repo import native_audio, native_audio_build


def test_build_native_capture_helper_compiles_packaged_swift_sources(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_dir = tmp_path / "src" / "meeting_memory" / "repo" / "native"
    source_dir.mkdir(parents=True)
    (source_dir / "A.swift").write_text("import Foundation\n", encoding="utf-8")
    (source_dir / "B.swift").write_text("let value = 1\n", encoding="utf-8")
    output = tmp_path / ".build" / native_audio.HELPER_NAME
    calls: list[list[str]] = []
    monkeypatch.setattr(native_audio_build, "_compatible_sdk_path", lambda: Path("/sdk"))

    def runner(command, **kwargs):
        assert kwargs["check"] is True
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        calls.append(command)
        output.write_bytes(b"binary")
        return subprocess.CompletedProcess(command, 0)

    result = native_audio.build_native_capture_helper(
        tmp_path,
        output,
        runner=runner,
        build_encoder=False,
    )

    assert result == output
    assert str(source_dir / "A.swift") in calls[0]
    assert str(source_dir / "B.swift") in calls[0]
    assert calls[0][-2:] == ["-o", str(output)]
    assert output.stat().st_mode & 0o111


def test_start_and_stop_native_capture_waits_for_ready_event(
    tmp_path: Path,
    monkeypatch,
) -> None:
    helper = tmp_path / native_audio.HELPER_NAME
    helper.write_bytes(b"binary")
    helper.chmod(0o755)
    output = tmp_path / "recording.wav"
    output.write_bytes(b"RIFF" + b"\0" * 64)
    process = FakeProcess()
    monkeypatch.setattr(native_audio, "native_capture_helper_path", lambda: helper)
    monkeypatch.setattr(native_audio.subprocess, "Popen", lambda *args, **kwargs: process)

    capture = native_audio.start_native_capture("full-meeting", output)
    result = capture.stop()

    assert result == output
    assert process.signals == [native_audio.signal.SIGINT]


def test_native_capture_rejects_async_error_even_when_helper_exits_zero(
    tmp_path: Path,
    monkeypatch,
) -> None:
    helper = tmp_path / native_audio.HELPER_NAME
    helper.write_bytes(b"binary")
    helper.chmod(0o755)
    output = tmp_path / "recording.wav"
    output.write_bytes(b"RIFF" + b"\0" * 64)
    process = DeferredErrorProcess()
    monkeypatch.setattr(native_audio, "native_capture_helper_path", lambda: helper)
    monkeypatch.setattr(native_audio.subprocess, "Popen", lambda *args, **kwargs: process)

    capture = native_audio.start_native_capture("full-meeting", output)

    with pytest.raises(native_audio.NativeAudioCaptureError, match="device disconnected"):
        capture.stop()


def test_native_capture_health_check_surfaces_failure_before_manual_stop(
    tmp_path: Path,
    monkeypatch,
) -> None:
    helper = tmp_path / native_audio.HELPER_NAME
    helper.write_bytes(b"binary")
    helper.chmod(0o755)
    process = DeferredErrorProcess()
    monkeypatch.setattr(native_audio, "native_capture_helper_path", lambda: helper)
    monkeypatch.setattr(native_audio.subprocess, "Popen", lambda *args, **kwargs: process)

    capture = native_audio.start_native_capture("full-meeting", tmp_path / "recording.wav")
    process.release.set()
    capture.reader.join(timeout=1)

    with pytest.raises(native_audio.NativeAudioCaptureError, match="device disconnected"):
        capture.check_health()


def test_native_check_rejects_fatal_event_with_zero_exit(monkeypatch, tmp_path: Path) -> None:
    helper = tmp_path / native_audio.HELPER_NAME
    helper.write_bytes(b"binary")
    helper.chmod(0o755)
    monkeypatch.setattr(native_audio, "native_capture_helper_path", lambda: helper)
    monkeypatch.setattr(
        native_audio.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            0,
            stdout=(
                '{"event":"supported","microphone":"AirPods"}\n'
                '{"event":"fatal","message":"late failure"}\n'
            ),
            stderr="",
        ),
    )

    with pytest.raises(native_audio.NativeAudioCaptureError, match="late failure"):
        native_audio.check_native_capture()


def test_convert_native_audio_uses_helper_and_validates_output(
    tmp_path: Path,
    monkeypatch,
) -> None:
    helper = tmp_path / native_audio.HELPER_NAME
    helper.write_bytes(b"binary")
    helper.chmod(0o755)
    wav_path = tmp_path / "recording.wav"
    wav_path.write_bytes(b"RIFF")
    m4a_path = tmp_path / "recording.m4a"
    calls: list[list[str]] = []
    monkeypatch.setattr(native_audio, "native_capture_helper_path", lambda: helper)

    def run(command, **kwargs):
        calls.append(command)
        m4a_path.write_bytes(b"m4a-data")
        return subprocess.CompletedProcess(
            command,
            0,
            stdout='{"event":"converted"}\n',
            stderr="",
        )

    monkeypatch.setattr(native_audio.subprocess, "run", run)

    result = native_audio.convert_native_audio(wav_path, m4a_path)

    assert result == m4a_path
    assert calls == [[str(helper), "convert", str(wav_path), "--output", str(m4a_path)]]


class FakeProcess:
    def __init__(self):
        self.stdout = io.StringIO(
            '{"event":"ready","mode":"full-meeting","microphone":"AirPods"}\n{"event":"stopped"}\n'
        )
        self.stderr = io.StringIO("")
        self.returncode: int | None = None
        self.signals: list[int] = []

    def poll(self):
        return self.returncode

    def send_signal(self, signal_number):
        self.signals.append(signal_number)

    def wait(self, timeout=None):
        del timeout
        self.returncode = 0
        return 0

    def terminate(self):
        self.returncode = 1

    def kill(self):
        self.returncode = -9


class DeferredErrorOutput:
    def __init__(self, release: threading.Event):
        self.release = release

    def __iter__(self):
        yield '{"event":"ready","mode":"full-meeting","microphone":"AirPods"}\n'
        self.release.wait(timeout=2)
        yield '{"event":"error","message":"device disconnected"}\n'


class DeferredErrorProcess(FakeProcess):
    def __init__(self):
        super().__init__()
        self.release = threading.Event()
        self.stdout = DeferredErrorOutput(self.release)

    def send_signal(self, signal_number):
        super().send_signal(signal_number)
        self.release.set()

    def wait(self, timeout=None):
        self.release.set()
        return super().wait(timeout)

    def terminate(self):
        self.release.set()
        super().terminate()

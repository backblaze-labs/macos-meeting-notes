"""Tests for the native macOS audio helper adapter."""

from __future__ import annotations

import io
import subprocess
from pathlib import Path

from meeting_memory.repo import native_audio


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
    monkeypatch.setattr(native_audio, "_compatible_sdk_path", lambda: Path("/sdk"))

    def runner(command, check, capture_output, text):
        assert check is True
        assert capture_output is True
        assert text is True
        calls.append(command)
        output.write_bytes(b"binary")
        return subprocess.CompletedProcess(command, 0)

    result = native_audio.build_native_capture_helper(tmp_path, output, runner=runner)

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
    assert calls == [
        [str(helper), "convert", str(wav_path), "--output", str(m4a_path)]
    ]


class FakeProcess:
    def __init__(self):
        self.stdout = io.StringIO(
            '{"event":"ready","mode":"full-meeting","microphone":"AirPods"}\n'
            '{"event":"stopped"}\n'
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

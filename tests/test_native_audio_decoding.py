"""Snapshot-only native decoding, cancellation and private-output checks."""

from __future__ import annotations

import json
import subprocess
import wave
from pathlib import Path

import pytest

from meeting_memory.repo import native_audio_decoding as decoding
from meeting_memory.repo.native_audio import NativeAudioCaptureError


class DecoderProcess:
    def __init__(self, command, *, output_frames=160, fail=False, wait=False, **kwargs):
        self.command = command
        self.kwargs = kwargs
        self.returncode = None
        self.stdout = self.stderr = None
        self.terminated = False
        self.fail = fail
        self.waiting = wait
        path = Path(command[-1]) / "decoded.wav"
        with wave.open(str(path), "wb") as pcm:
            pcm.setnchannels(1)
            pcm.setsampwidth(2)
            pcm.setframerate(16_000)
            pcm.writeframes(b"\0\0" * 160)
        self.output = json.dumps(
            {"event": "decoded", "sample_rate": 16_000, "channels": 1, "frames": output_frames}
        )

    def communicate(self, *, timeout):
        if self.waiting:
            raise subprocess.TimeoutExpired(self.command, timeout)
        self.returncode = 1 if self.fail else 0
        return self.output, "private diagnostic must not surface"

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def wait(self, *, timeout):
        return self.returncode


def snapshot(tmp_path):
    path = tmp_path / "audio.m4a"
    path.write_bytes(b"stable private snapshot")
    audio = path.open("rb")
    path.unlink()
    return audio


def test_decode_consumes_only_readonly_descriptor_and_cleans_output(tmp_path, monkeypatch):
    processes = []
    monkeypatch.setenv("ASSEMBLYAI_API_KEY", "sentinel")

    def popen(command, **kwargs):
        process = DecoderProcess(command, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(decoding.subprocess, "Popen", popen)
    with snapshot(tmp_path) as audio:
        with decoding.decoded_native_audio(audio, helper=Path("/native/helper")) as path:
            assert path.stat().st_mode & 0o777 == 0o600
            assert path.parent.stat().st_mode & 0o777 == 0o700
            assert path.exists()
            assert processes[0].command[:3] == ["/native/helper", "decode-fd", str(audio.fileno())]
            assert processes[0].kwargs["pass_fds"] == (audio.fileno(),)
            assert processes[0].kwargs["close_fds"] is True
            assert "ASSEMBLYAI_API_KEY" not in processes[0].kwargs["env"]
        assert not path.parent.exists()


def test_decode_rejects_writable_snapshot_before_spawning(tmp_path, monkeypatch):
    monkeypatch.setattr(decoding.subprocess, "Popen", lambda *_a, **_kw: pytest.fail("spawned"))
    with (tmp_path / "audio.m4a").open("w+b") as audio:
        audio.write(b"audio")
        audio.flush()
        with pytest.raises(NativeAudioCaptureError, match="read-only"):
            with decoding.decoded_native_audio(audio, helper=Path("/native/helper")):
                pytest.fail("yielded")


@pytest.mark.parametrize(
    "output_frames,fail", [(0, False), (159, False), (161, False), (160, True)]
)
def test_decode_rejects_invalid_result_without_exposing_native_detail(
    tmp_path, monkeypatch, output_frames, fail
):
    directories = []

    def popen(command, **kwargs):
        directories.append(Path(command[-1]))
        return DecoderProcess(command, output_frames=output_frames, fail=fail, **kwargs)

    monkeypatch.setattr(decoding.subprocess, "Popen", popen)
    with snapshot(tmp_path) as audio:
        with pytest.raises(NativeAudioCaptureError) as error:
            with decoding.decoded_native_audio(audio, helper=Path("/native/helper")):
                pytest.fail("yielded invalid output")
    assert "private diagnostic" not in str(error.value)
    assert not directories[0].exists()


def test_cancelled_decode_terminates_child_and_removes_private_files(tmp_path, monkeypatch):
    processes = []
    polls = 0

    def cancelled():
        nonlocal polls
        polls += 1
        return polls >= 3

    def popen(command, **kwargs):
        process = DecoderProcess(command, wait=True, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(decoding.subprocess, "Popen", popen)
    with snapshot(tmp_path) as audio:
        with pytest.raises(NativeAudioCaptureError, match="cancelled"):
            with decoding.decoded_native_audio(
                audio, helper=Path("/native/helper"), cancelled=cancelled
            ):
                pytest.fail("yielded cancelled audio")
    assert processes[0].terminated
    assert not Path(processes[0].command[-1]).exists()


def test_decode_timeout_terminates_child_and_cleans_temp(tmp_path, monkeypatch):
    processes = []
    clock = iter([0, 2])
    monkeypatch.setattr(decoding.time, "monotonic", lambda: next(clock))

    def popen(command, **kwargs):
        process = DecoderProcess(command, wait=True, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(decoding.subprocess, "Popen", popen)
    with snapshot(tmp_path) as audio:
        with pytest.raises(NativeAudioCaptureError, match="timed out"):
            with decoding.decoded_native_audio(
                audio, helper=Path("/native/helper"), timeout_seconds=1
            ):
                pytest.fail("yielded timed out audio")
    assert processes[0].terminated
    assert not Path(processes[0].command[-1]).exists()


def test_consumer_failure_cleans_decoded_audio(tmp_path, monkeypatch):
    monkeypatch.setattr(decoding.subprocess, "Popen", DecoderProcess)
    decoded_parent = None
    failure = None
    try:
        with snapshot(tmp_path) as audio:
            with decoding.decoded_native_audio(audio, helper=Path("/native/helper")) as path:
                decoded_parent = path.parent
                raise RuntimeError("consumer")
    except RuntimeError as error:
        failure = str(error)
    assert failure == "consumer"
    assert decoded_parent is not None
    assert not decoded_parent.exists()


def test_decoded_output_cannot_follow_symlink(tmp_path, monkeypatch):
    target = tmp_path / "other-file"
    target.write_bytes(b"do not modify")
    initial_mode = target.stat().st_mode

    def popen(command, **kwargs):
        process = DecoderProcess(command, **kwargs)
        output = Path(command[-1]) / "decoded.wav"
        output.unlink()
        output.symlink_to(target)
        return process

    monkeypatch.setattr(decoding.subprocess, "Popen", popen)
    with snapshot(tmp_path) as audio:
        with pytest.raises(NativeAudioCaptureError, match="verified"):
            with decoding.decoded_native_audio(audio, helper=Path("/native/helper")):
                pytest.fail("followed symlink")
    assert target.read_bytes() == b"do not modify"
    assert target.stat().st_mode == initial_mode


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_decode_rejects_invalid_timeout_before_spawn(tmp_path, monkeypatch, timeout):
    monkeypatch.setattr(decoding.subprocess, "Popen", lambda *_a, **_kw: pytest.fail("spawned"))
    with snapshot(tmp_path) as audio:
        with pytest.raises(ValueError, match="timeout"):
            with decoding.decoded_native_audio(
                audio, helper=Path("/native/helper"), timeout_seconds=timeout
            ):
                pytest.fail("yielded")


def test_decode_launch_failure_cleans_private_directory_and_is_actionable(tmp_path, monkeypatch):
    directories = []

    def popen(command, **kwargs):
        directories.append(Path(command[-1]))
        raise OSError("private launch diagnostic")

    monkeypatch.setattr(decoding.subprocess, "Popen", popen)
    with snapshot(tmp_path) as audio:
        with pytest.raises(NativeAudioCaptureError, match="Reinstall") as error:
            with decoding.decoded_native_audio(audio, helper=Path("/native/helper")):
                pytest.fail("yielded")
    assert "private launch diagnostic" not in str(error.value)
    assert not directories[0].exists()


def test_decode_cancellation_before_start_never_spawns(tmp_path, monkeypatch):
    monkeypatch.setattr(decoding.subprocess, "Popen", lambda *_a, **_kw: pytest.fail("spawned"))
    with snapshot(tmp_path) as audio:
        with pytest.raises(NativeAudioCaptureError, match="cancelled"):
            with decoding.decoded_native_audio(
                audio, helper=Path("/native/helper"), cancelled=lambda: True
            ):
                pytest.fail("yielded")


def test_decoder_ignoring_terminate_is_killed_and_joined():
    class StubbornProcess:
        stdout = stderr = None
        killed = False
        waits = 0

        def poll(self):
            return None

        def terminate(self):
            pass

        def wait(self, *, timeout):
            self.waits += 1
            if not self.killed:
                raise subprocess.TimeoutExpired("decoder", timeout)
            return -9

        def kill(self):
            self.killed = True

    process = StubbornProcess()
    decoding._stop_decoder(process)
    assert process.killed
    assert process.waits == 2

import math
import os
import shlex
import struct
import subprocess
import wave
from pathlib import Path

import pytest

from meeting_memory.repo import native_audio_validation
from meeting_memory.repo.native_audio import (
    NativeAudioCaptureError,
    build_native_capture_helper,
    convert_native_audio,
)
from meeting_memory.types.runtime_layout import NATIVE_ENCODER_NAME


def test_native_m4a_validator_requires_one_complete_fact_event(
    tmp_path: Path,
    monkeypatch,
) -> None:
    helper = tmp_path / "helper"
    helper.write_bytes(b"binary")
    helper.chmod(0o755)
    monkeypatch.setattr(native_audio_validation, "native_capture_helper_path", lambda: helper)
    calls: list[list[str]] = []

    def runner(command, **_kwargs):
        calls.append(command)
        assert _kwargs["timeout"] == native_audio_validation.NATIVE_VALIDATION_TIMEOUT_SECONDS
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                '{"event":"validated","codec":"aac","packets":4,'
                '"duration_seconds":1.25,"sample_rate":16000,"channels":1}\n'
            ),
            stderr="",
        )

    path = tmp_path / "recording.m4a"
    path.write_bytes(b"candidate")
    native_audio_validation.validate_native_m4a(path, runner=runner)

    assert calls == [[str(helper), "validate", str(path)]]


def test_native_m4a_validator_contains_helper_timeout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    helper = tmp_path / "helper"
    helper.write_bytes(b"binary")
    helper.chmod(0o755)
    monkeypatch.setattr(native_audio_validation, "native_capture_helper_path", lambda: helper)
    candidate = tmp_path / "candidate.m4a"
    candidate.write_bytes(b"candidate")
    descriptor = os.open(candidate, os.O_RDONLY)
    candidate.unlink()
    snapshot_directory: Path | None = None

    def runner(command, **kwargs):
        nonlocal snapshot_directory
        snapshot_directory = Path(command[3])
        (snapshot_directory / "candidate.m4a").write_bytes(b"private audio")
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    try:
        with pytest.raises(NativeAudioCaptureError, match="validation timed out"):
            native_audio_validation.validate_native_m4a(
                Path(f"/dev/fd/{descriptor}"),
                runner=runner,
            )
    finally:
        os.close(descriptor)
    assert snapshot_directory is not None
    assert not snapshot_directory.exists()


def test_native_validator_inherits_read_only_descriptor_snapshot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    helper = tmp_path / "helper"
    helper.write_bytes(b"binary")
    helper.chmod(0o755)
    monkeypatch.setattr(native_audio_validation, "native_capture_helper_path", lambda: helper)
    candidate = tmp_path / "candidate.m4a"
    candidate.write_bytes(b"candidate")
    descriptor = os.open(candidate, os.O_RDONLY)
    candidate.unlink()

    def runner(command, **kwargs):
        assert kwargs["pass_fds"] == (descriptor,)
        assert command[:3] == [str(helper), "validate-fd", str(descriptor)]
        snapshot_directory = Path(command[3])
        assert snapshot_directory.is_dir()
        assert snapshot_directory.stat().st_mode & 0o777 == 0o700
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                '{"event":"validated","codec":"aac","packets":1,'
                '"duration_seconds":1,"sample_rate":16000,"channels":1}\n'
            ),
            stderr="",
        )

    try:
        native_audio_validation.validate_native_m4a(
            Path(f"/dev/fd/{descriptor}"),
            runner=runner,
        )
    finally:
        os.close(descriptor)


@pytest.mark.parametrize(
    "stdout,returncode",
    [
        ("", 0),
        ('{"event":"validated","codec":"aac","packets":0}\n', 0),
        (
            '{"event":"validated","codec":"aac","packets":1,'
            '"duration_seconds":1,"sample_rate":16000,"channels":1}\n'
            '{"event":"other"}\n',
            0,
        ),
        ('{"event":"fatal","message":"truncated"}\n', 1),
    ],
)
def test_native_m4a_validator_rejects_missing_or_contradictory_facts(
    tmp_path: Path,
    monkeypatch,
    stdout: str,
    returncode: int,
) -> None:
    helper = tmp_path / "helper"
    helper.write_bytes(b"binary")
    helper.chmod(0o755)
    monkeypatch.setattr(native_audio_validation, "native_capture_helper_path", lambda: helper)

    with pytest.raises(NativeAudioCaptureError):
        candidate = tmp_path / "bad.m4a"
        candidate.write_bytes(b"candidate")
        native_audio_validation.validate_native_m4a(
            candidate,
            runner=lambda command, **_kwargs: subprocess.CompletedProcess(
                command, returncode, stdout=stdout, stderr=""
            ),
        )


def test_native_m4a_validator_rejects_symlink_before_helper(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = tmp_path / "target.m4a"
    target.write_bytes(b"secret")
    link = tmp_path / "link.m4a"
    link.symlink_to(target)
    called = False

    def runner(*_args, **_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(
        native_audio_validation,
        "native_capture_helper_path",
        lambda: tmp_path / "helper",
    )
    with pytest.raises(OSError):
        native_audio_validation.validate_native_m4a(link, runner=runner)
    assert called is False


def test_native_m4a_validator_accepts_real_offline_conversion(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = Path(__file__).resolve().parents[1]
    helper = build_native_capture_helper(project, tmp_path / "MeetingMemoryCapture")
    wav_path = tmp_path / "recording.wav"
    with wave.open(str(wav_path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16_000)
        frames = b"".join(
            struct.pack("<h", round(4_000 * math.sin(2 * math.pi * 440 * index / 16_000)))
            for index in range(16_000)
        )
        audio.writeframes(frames)
    m4a_path = tmp_path / "recording.m4a"
    monkeypatch.setattr(native_audio_validation, "native_capture_helper_path", lambda: helper)
    monkeypatch.setattr(
        "meeting_memory.repo.native_audio.native_capture_helper_path",
        lambda: helper,
    )

    convert_native_audio(wav_path, m4a_path)
    native_audio_validation.validate_native_m4a(m4a_path)
    descriptor = os.open(m4a_path, os.O_RDONLY)
    m4a_path.unlink()
    try:
        native_audio_validation.validate_native_m4a(Path(f"/dev/fd/{descriptor}"))
    finally:
        os.close(descriptor)


def test_native_conversion_fallback_uses_only_the_fixed_sibling_command(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = Path(__file__).resolve().parents[1]
    helper = build_native_capture_helper(
        project,
        tmp_path / "MeetingMemoryCapture",
        build_encoder=False,
    )
    encoder = helper.with_name(NATIVE_ENCODER_NAME)
    arguments = tmp_path / "arguments.txt"
    encoder.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$@\" > {shlex.quote(str(arguments))}\n"
        'for output_path in "$@"; do :; done\n'
        'printf "fake-m4a" > "$output_path"\n',
        encoding="utf-8",
    )
    encoder.chmod(0o755)
    invalid_wav = tmp_path / "invalid.wav"
    invalid_wav.write_bytes(b"not-a-wave")
    output = tmp_path / "recording.m4a"
    monkeypatch.setattr(
        "meeting_memory.repo.native_audio.native_capture_helper_path",
        lambda: helper,
    )

    convert_native_audio(invalid_wav, output)

    assert output.read_bytes() == b"fake-m4a"
    assert arguments.read_text(encoding="utf-8").splitlines() == [
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",
        "-i",
        str(invalid_wav),
        "-map",
        "0:a:0",
        "-vn",
        "-sn",
        "-dn",
        "-c:a",
        "aac",
        "-b:a",
        "48k",
        "-ar",
        "16000",
        "-ac",
        "1",
        "-movflags",
        "+faststart",
        str(output),
    ]

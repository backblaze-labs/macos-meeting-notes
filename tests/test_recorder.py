"""Tests for the recorder service."""

from __future__ import annotations

import struct
import wave
from datetime import UTC, datetime
from pathlib import Path

import pytest

from meeting_memory.repo.audio_device import AudioDeviceInfo
from meeting_memory.service.recorder import RecorderService


def test_recorder_start_stop_writes_wav_and_converts_to_m4a(tmp_path: Path) -> None:
    times = iter(
        [
            datetime(2026, 6, 11, 9, 0, tzinfo=UTC),
            datetime(2026, 6, 11, 9, 3, tzinfo=UTC),
        ]
    )
    stream_holder: dict[str, FakeStream] = {}
    converted: list[tuple[Path, Path]] = []

    recorder = RecorderService(
        audio_device="Meeting Aggregate",
        temp_dir=tmp_path,
        now=lambda: next(times),
        device_lookup=lambda name: AudioDeviceInfo(index=7, name=name, max_input_channels=2),
        stream_factory=lambda **kwargs: stream_holder.setdefault("stream", FakeStream(**kwargs)),
        converter=lambda wav, m4a: _copy_conversion(wav, m4a, converted),
    )

    session = recorder.start("Product Sync")
    assert session is not None
    assert recorder.start("Ignored") is None
    stream_holder["stream"].emit(b"\x01\x02\x03\x04")

    result = recorder.stop()

    assert result is not None
    assert recorder.is_recording is False
    assert result.meta.slug == "2026-06-11_09-00_product-sync"
    assert result.meta.duration_minutes == 3
    assert result.audio_path.suffix == ".m4a"
    assert result.audio_path.exists()
    assert not result.wav_path.exists()
    assert converted == [(result.wav_path, result.audio_path)]
    assert stream_holder["stream"].device_index == 7
    assert stream_holder["stream"].channels == 2
    assert stream_holder["stream"].ever_started is True
    assert stream_holder["stream"].closed is True


def test_recorder_downmixes_multichannel_input_to_mono(tmp_path: Path) -> None:
    stream_holder: dict[str, FakeStream] = {}
    recorder = RecorderService(
        audio_device="Meeting Aggregate",
        temp_dir=tmp_path,
        now=lambda: datetime(2026, 6, 11, 9, 0, tzinfo=UTC),
        device_lookup=lambda name: AudioDeviceInfo(index=7, name=name, max_input_channels=2),
        stream_factory=lambda **kwargs: stream_holder.setdefault("stream", FakeStream(**kwargs)),
        converter=lambda wav, m4a: m4a.write_bytes(wav.read_bytes()),
    )

    recorder.start("Product Sync")
    stream_holder["stream"].emit_audio(FakeMultiChannelAudio([(2000, 0), (0, 4000)]))
    result = recorder.stop()

    assert result is not None
    with wave.open(str(result.audio_path), "rb") as audio_file:
        assert audio_file.getnchannels() == 1
        assert audio_file.readframes(2) == struct.pack("<hh", 1000, 2000)


def test_recorder_stop_without_session_is_noop(tmp_path: Path) -> None:
    recorder = RecorderService(
        audio_device="Meeting Aggregate",
        temp_dir=tmp_path,
        device_lookup=lambda name: AudioDeviceInfo(index=1, name=name, max_input_channels=1),
    )

    assert recorder.stop() is None


def test_recorder_start_failure_cleans_partial_state(tmp_path: Path) -> None:
    streams: list[FakeStream] = []
    fail_next = True

    def stream_factory(**kwargs):
        nonlocal fail_next
        stream = FakeStream(**kwargs)
        stream.fail_on_start = fail_next
        fail_next = False
        streams.append(stream)
        return stream

    recorder = RecorderService(
        audio_device="Meeting Aggregate",
        temp_dir=tmp_path,
        now=lambda: datetime(2026, 6, 11, 9, 0, tzinfo=UTC),
        device_lookup=lambda name: AudioDeviceInfo(index=1, name=name, max_input_channels=1),
        stream_factory=stream_factory,
        converter=lambda wav, m4a: m4a.write_bytes(wav.read_bytes()),
    )

    with pytest.raises(RuntimeError, match="stream unavailable"):
        recorder.start("Product Sync")

    assert recorder.is_recording is False
    assert recorder.active_session is None
    assert streams[0].closed is True

    assert recorder.start("Product Sync") is not None
    assert recorder.is_recording is True


class FakeAudio:
    def __init__(self, payload: bytes):
        self.payload = payload

    def tobytes(self) -> bytes:
        return self.payload


class FakeMultiChannelAudio:
    def __init__(self, frames: list[tuple[int, ...]]):
        self.frames = frames
        self.shape = (len(frames), len(frames[0]))

    def astype(self, dtype: str):
        assert dtype == "int32"
        return FakeMeanableAudio(self.frames)


class FakeMeanableAudio:
    def __init__(self, frames: list[tuple[int, ...]]):
        self.frames = frames

    def mean(self, axis: int):
        assert axis == 1
        return FakeClippableSamples([sum(frame) / len(frame) for frame in self.frames])


class FakeClippableSamples:
    def __init__(self, samples: list[float]):
        self.samples = samples

    def clip(self, low: int, high: int):
        return FakeInt16Samples([min(high, max(low, int(sample))) for sample in self.samples])


class FakeInt16Samples:
    def __init__(self, samples: list[int]):
        self.samples = samples

    def astype(self, dtype: str):
        assert dtype == "int16"
        return self

    def tobytes(self) -> bytes:
        return struct.pack("<" + "h" * len(self.samples), *self.samples)


class FakeStream:
    def __init__(self, *, device_index: int, sample_rate: int, channels: int, callback):
        self.device_index = device_index
        self.sample_rate = sample_rate
        self.channels = channels
        self.callback = callback
        self.started = False
        self.ever_started = False
        self.closed = False
        self.fail_on_start = False

    def start(self) -> None:
        if self.fail_on_start:
            raise RuntimeError("stream unavailable")
        self.started = True
        self.ever_started = True

    def stop(self) -> None:
        self.started = False

    def close(self) -> None:
        self.closed = True

    def emit(self, payload: bytes) -> None:
        self.callback(FakeAudio(payload), 1, None, None)

    def emit_audio(self, audio) -> None:
        self.callback(audio, len(audio.frames), None, None)


def _copy_conversion(wav_path: Path, m4a_path: Path, converted: list[tuple[Path, Path]]) -> None:
    converted.append((wav_path, m4a_path))
    m4a_path.write_bytes(wav_path.read_bytes())

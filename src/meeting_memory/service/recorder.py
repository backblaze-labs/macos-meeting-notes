"""Recording service for manual start/stop flows."""

from __future__ import annotations

import subprocess
import tempfile
import threading
import wave
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from meeting_memory.repo.audio_device import find_audio_device, open_input_stream
from meeting_memory.types.meeting import MeetingMeta, build_meeting_slug

SAMPLE_RATE = 16_000
CHANNELS = 1
SAMPLE_WIDTH_BYTES = 2


@dataclass(frozen=True)
class RecordingSession:
    meta: MeetingMeta
    wav_path: Path


@dataclass(frozen=True)
class RecordingResult:
    meta: MeetingMeta
    audio_path: Path
    wav_path: Path


@dataclass
class RecorderService:
    audio_device: str
    temp_dir: Path = field(default_factory=lambda: Path(tempfile.gettempdir()))
    now: Callable[[], datetime] = field(
        default_factory=lambda: lambda: datetime.now().astimezone()
    )
    device_lookup: Callable[[str], Any] = find_audio_device
    stream_factory: Callable[..., Any] = open_input_stream
    converter: Callable[[Path, Path], None] = field(default=None)

    def __post_init__(self) -> None:
        if self.converter is None:
            self.converter = convert_wav_to_m4a
        self._lock = threading.RLock()
        self._wave_file: wave.Wave_write | None = None
        self._stream = None
        self._session: RecordingSession | None = None

    @property
    def is_recording(self) -> bool:
        return self._session is not None

    @property
    def active_session(self) -> RecordingSession | None:
        return self._session

    def start(
        self,
        calendar_title: str = "Untitled",
        *,
        speaker_candidates: tuple[str, ...] = (),
    ) -> RecordingSession | None:
        with self._lock:
            if self._session is not None:
                return None

            started_at = self.now()
            title = calendar_title or "Untitled"
            slug = build_meeting_slug(started_at, title)
            wav_path = self.temp_dir / f"meeting-memory-{slug}.wav"
            device = self.device_lookup(self.audio_device)
            input_channels = max(CHANNELS, int(device.max_input_channels or CHANNELS))

            self.temp_dir.mkdir(parents=True, exist_ok=True)
            wave_file = wave.open(str(wav_path), "wb")
            stream = None

            try:
                wave_file.setnchannels(CHANNELS)
                wave_file.setsampwidth(SAMPLE_WIDTH_BYTES)
                wave_file.setframerate(SAMPLE_RATE)
                self._wave_file = wave_file
                stream = self.stream_factory(
                    device_index=device.index,
                    sample_rate=SAMPLE_RATE,
                    channels=input_channels,
                    callback=self._audio_callback,
                )
                self._stream = stream
                stream.start()
            except Exception:
                self._wave_file = None
                self._stream = None
                with suppress(Exception):
                    if stream is not None:
                        stream.stop()
                with suppress(Exception):
                    if stream is not None:
                        stream.close()
                wave_file.close()
                with suppress(OSError):
                    wav_path.unlink()
                raise

            session = RecordingSession(
                meta=MeetingMeta(
                    slug=slug,
                    started_at=started_at,
                    calendar_title=title,
                    speaker_candidates=speaker_candidates,
                ),
                wav_path=wav_path,
            )
            self._session = session
            return session

    def stop(self) -> RecordingResult | None:
        with self._lock:
            session = self._session
            if session is None:
                return None

            stream = self._stream
            wave_file = self._wave_file
            self._session = None
            self._stream = None
            self._wave_file = None

        if stream is not None:
            stream.stop()
            stream.close()
        if wave_file is not None:
            wave_file.close()

        duration_minutes = max(
            0,
            round((self.now() - session.meta.started_at).total_seconds() / 60),
        )
        meta = MeetingMeta(
            slug=session.meta.slug,
            started_at=session.meta.started_at,
            calendar_title=session.meta.calendar_title,
            duration_minutes=duration_minutes,
            speaker_candidates=session.meta.speaker_candidates,
        )
        m4a_path = session.wav_path.with_suffix(".m4a")
        self.converter(session.wav_path, m4a_path)
        with suppress(OSError):
            session.wav_path.unlink()
        return RecordingResult(meta=meta, audio_path=m4a_path, wav_path=session.wav_path)

    def _audio_callback(self, indata, frames, time_info, status) -> None:
        del frames, time_info, status
        with self._lock:
            if self._wave_file is not None:
                self._wave_file.writeframes(_mono_pcm16_bytes(indata))


def _mono_pcm16_bytes(indata) -> bytes:
    shape = getattr(indata, "shape", ())
    if len(shape) < 2 or shape[1] <= 1:
        return indata.tobytes()

    mono = indata.astype("int32").mean(axis=1).clip(-32768, 32767).astype("int16")
    return mono.tobytes()


def convert_wav_to_m4a(wav_path: Path, m4a_path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(wav_path),
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            str(m4a_path),
        ],
        check=True,
        capture_output=True,
    )

"""Recording service for manual start/stop flows."""

from __future__ import annotations

import tempfile
import threading
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from meeting_memory.repo.native_audio import convert_native_audio, start_native_capture
from meeting_memory.types.meeting import MeetingMeta, build_meeting_slug

DEFAULT_CAPTURE_MODE = "full-meeting"


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
    capture_mode: str = DEFAULT_CAPTURE_MODE
    temp_dir: Path = field(default_factory=lambda: Path(tempfile.gettempdir()))
    now: Callable[[], datetime] = field(
        default_factory=lambda: lambda: datetime.now().astimezone()
    )
    capture_starter: Callable[[str, Path], Any] = start_native_capture
    converter: Callable[[Path, Path], None] = field(default=None)

    def __post_init__(self) -> None:
        if self.converter is None:
            self.converter = convert_wav_to_m4a
        self._lock = threading.RLock()
        self._capture = None
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

            self.temp_dir.mkdir(parents=True, exist_ok=True)
            try:
                self._capture = self.capture_starter(self.capture_mode, wav_path)
            except Exception:
                self._capture = None
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

            capture = self._capture
            self._session = None
            self._capture = None

        if capture is not None:
            capture.stop()

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

def convert_wav_to_m4a(wav_path: Path, m4a_path: Path) -> None:
    convert_native_audio(wav_path, m4a_path)

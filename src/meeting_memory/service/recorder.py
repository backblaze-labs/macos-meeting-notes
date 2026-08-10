"""Recording service for manual start/stop flows."""

from __future__ import annotations

import os
import stat
import threading
import wave
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from meeting_memory.config.defaults import DEFAULT_MEETINGS_DIR
from meeting_memory.repo.native_audio import convert_native_audio, start_native_capture
from meeting_memory.service.recovery_index import (
    create_recovery_session,
    pin_recovery_source,
    update_recovery_session_meta,
)
from meeting_memory.types.meeting import MeetingMeta, build_meeting_slug
from meeting_memory.types.recovery import RecoveryIndexEntry

DEFAULT_CAPTURE_MODE = "full-meeting"


@dataclass(frozen=True)
class RecordingSession:
    meta: MeetingMeta
    wav_path: Path
    recovery: RecoveryIndexEntry | None = None


@dataclass(frozen=True)
class RecordingResult:
    meta: MeetingMeta
    audio_path: Path
    wav_path: Path
    recovery: RecoveryIndexEntry | None = None


@dataclass
class RecorderService:
    capture_mode: str = DEFAULT_CAPTURE_MODE
    temp_dir: Path = field(
        default_factory=lambda: Path(DEFAULT_MEETINGS_DIR).expanduser()
        / ".meeting-memory-staging"
        / "recordings"
    )
    now: Callable[[], datetime] = field(
        default_factory=lambda: lambda: datetime.now().astimezone()
    )
    capture_starter: Callable[[str, Path], Any] = start_native_capture
    converter: Callable[[Path, Path], None] | None = None
    def __post_init__(self) -> None:
        self._lock = threading.RLock()
        self._capture_io_lock = threading.Lock()
        self._capture = None
        self._session: RecordingSession | None = None
        self._stopping = False

    @property
    def is_recording(self) -> bool:
        with self._lock:
            return self._session is not None

    @property
    def is_stopping(self) -> bool:
        with self._lock:
            return self._stopping

    @property
    def active_session(self) -> RecordingSession | None:
        with self._lock:
            return self._session

    def start(
        self,
        calendar_title: str = "Untitled",
        *,
        speaker_candidates: tuple[str, ...] = (),
    ) -> RecordingSession | None:
        with self._lock:
            if self._session is not None or self._stopping:
                return None

            started_at = self.now()
            title = calendar_title or "Untitled"
            slug = build_meeting_slug(started_at, title)
            meta = MeetingMeta(
                slug=slug,
                started_at=started_at,
                calendar_title=title,
                speaker_candidates=speaker_candidates,
            )
            recovery = create_recovery_session(self.temp_dir, meta)
            wav_path = recovery.source_path
            try:
                self._capture = self.capture_starter(self.capture_mode, wav_path)
            except Exception:
                self._capture = None
                _discard_empty_session(recovery)
                raise

            session = RecordingSession(
                meta=meta,
                wav_path=wav_path,
                recovery=recovery,
            )
            self._session = session
            return session

    def stop(self) -> RecordingResult | None:
        with self._lock:
            session = self._session
            if session is None or self._stopping:
                return None
            capture = self._capture
            self._stopping = True

        try:
            with self._capture_io_lock:
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
            if session.recovery is None:
                raise RuntimeError("recording session has no recovery index")
            recovery = update_recovery_session_meta(session.recovery, meta)
            if self.converter is not None:
                m4a_path = recovery.source_path.with_suffix(".m4a")
                self.converter(recovery.source_path, m4a_path)
                recovery.source_path.unlink()
                return RecordingResult(meta, m4a_path, recovery.source_path)
            recovery = pin_recovery_source(recovery)
            return RecordingResult(
                meta=meta,
                audio_path=recovery.source_path,
                wav_path=recovery.source_path,
                recovery=recovery,
            )
        finally:
            with self._lock:
                if self._session is session:
                    self._session = None
                    self._capture = None
                self._stopping = False

    def check_health(self) -> None:
        with self._lock:
            capture = self._capture
            session = self._session
            if session is None or capture is None or self._stopping:
                return
            checker = getattr(capture, "check_health", None)
            if checker is None:
                return

        with self._capture_io_lock:
            with self._lock:
                if (
                    self._capture is not capture
                    or self._session is not session
                    or self._stopping
                ):
                    return
            try:
                checker()
            except Exception:
                with self._lock:
                    should_report = (
                        self._capture is capture
                        and self._session is session
                        and not self._stopping
                    )
                    if should_report:
                        self._capture = None
                        self._session = None
                if should_report:
                    raise


def _discard_empty_session(entry: RecoveryIndexEntry) -> None:
    """Remove only a session with no recoverable recorded frames."""

    try:
        source = os.stat(entry.source_path, follow_symlinks=False)
    except FileNotFoundError:
        source = None
    except OSError:
        return
    if source is not None:
        if not stat.S_ISREG(source.st_mode):
            return
        if source.st_size > 0 and _wav_has_frames(entry.source_path):
            return
        with suppress(OSError):
            entry.source_path.unlink()
    with suppress(OSError):
        entry.index_path.unlink()
    with suppress(OSError):
        entry.session_directory.rmdir()


def _wav_has_frames(path: Path) -> bool:
    try:
        with wave.open(str(path), "rb") as audio:
            return audio.getnframes() > 0
    except (EOFError, OSError, wave.Error):
        # A malformed non-empty file may contain recoverable partial audio.
        return True


def convert_wav_to_m4a(wav_path: Path, m4a_path: Path) -> None:
    """Legacy compatibility wrapper; runtime conversion happens during commit."""

    convert_native_audio(wav_path, m4a_path)

"""Recover interrupted temporary recordings."""

from __future__ import annotations

import wave
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from meeting_memory.service.recorder import convert_wav_to_m4a
from meeting_memory.types.meeting import MeetingMeta

TEMP_RECORDING_PREFIX = "meeting-memory-"
TEMP_RECORDING_GLOB = f"{TEMP_RECORDING_PREFIX}*.wav"


@dataclass(frozen=True)
class RecoveredRecording:
    wav_path: Path
    meta: MeetingMeta

    @property
    def audio_path(self) -> Path:
        return self.wav_path.with_suffix(".m4a")


def find_recovered_recordings(temp_dir: Path) -> list[RecoveredRecording]:
    temp_dir = temp_dir.expanduser()
    if not temp_dir.exists():
        return []

    recordings = [
        recording
        for path in sorted(temp_dir.glob(TEMP_RECORDING_GLOB))
        if path.is_file()
        and path.stat().st_size > 0
        and not path.with_suffix(".m4a").exists()
        and (recording := recovered_recording_from_path(path)) is not None
    ]
    return recordings


def recovered_recording_from_path(path: Path) -> RecoveredRecording | None:
    slug = _slug_from_path(path)
    if slug is None:
        return None

    started_at = _started_at_from_slug(slug) or datetime.fromtimestamp(
        path.stat().st_mtime
    ).astimezone()
    return RecoveredRecording(
        wav_path=path,
        meta=MeetingMeta(
            slug=slug,
            started_at=started_at,
            calendar_title=_title_from_slug(slug),
            duration_minutes=_duration_minutes(path),
        ),
    )


def convert_recovered_recording(
    recording: RecoveredRecording,
    converter: Callable[[Path, Path], None] = convert_wav_to_m4a,
) -> Path:
    converter(recording.wav_path, recording.audio_path)
    with suppress(OSError):
        recording.wav_path.unlink()
    return recording.audio_path


def _slug_from_path(path: Path) -> str | None:
    stem = path.stem
    if not stem.startswith(TEMP_RECORDING_PREFIX):
        return None
    slug = stem.removeprefix(TEMP_RECORDING_PREFIX)
    return slug or None


def _started_at_from_slug(slug: str) -> datetime | None:
    try:
        return datetime.strptime(slug[:16], "%Y-%m-%d_%H-%M").astimezone()
    except ValueError:
        return None


def _title_from_slug(slug: str) -> str:
    title_slug = slug[17:] if len(slug) > 17 else ""
    title = title_slug.replace("-", " ").strip().title()
    return title or "Recovered Recording"


def _duration_minutes(path: Path) -> int:
    try:
        with wave.open(str(path), "rb") as audio_file:
            frames = audio_file.getnframes()
            rate = audio_file.getframerate()
    except (OSError, EOFError, wave.Error):
        return 0
    if rate <= 0:
        return 0
    return max(0, round(frames / rate / 60))

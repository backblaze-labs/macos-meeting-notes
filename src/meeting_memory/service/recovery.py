"""Recover interrupted temporary recordings."""

from __future__ import annotations

import json
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
PENDING_AUDIO_GLOB = f"{TEMP_RECORDING_PREFIX}*.pending.json"


@dataclass(frozen=True)
class RecoveredRecording:
    wav_path: Path
    meta: MeetingMeta
    ready_audio_path: Path | None = None
    marker_path: Path | None = None

    @property
    def audio_path(self) -> Path:
        return self.ready_audio_path or self.wav_path.with_suffix(".m4a")


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
    pending_audio = [
        recording
        for marker in sorted(temp_dir.glob(PENDING_AUDIO_GLOB))
        if (recording := _pending_recording_from_marker(marker)) is not None
    ]
    return sorted([*recordings, *pending_audio], key=lambda item: item.meta.started_at)


def mark_audio_for_recovery(audio_path: Path, meta: MeetingMeta) -> Path:
    if not audio_path.is_file() or audio_path.stat().st_size == 0:
        raise ValueError("recovery audio must exist and contain data")
    marker = audio_path.with_suffix(".pending.json")
    temporary = marker.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {
                "audio_file": audio_path.name,
                "slug": meta.slug,
                "started_at": meta.started_at.isoformat(),
                "calendar_title": meta.calendar_title,
                "duration_minutes": meta.duration_minutes,
                "speaker_candidates": list(meta.speaker_candidates),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    temporary.replace(marker)
    return marker


def recovered_recording_from_path(path: Path) -> RecoveredRecording | None:
    slug = _slug_from_path(path)
    if slug is None:
        return None
    duration_minutes = _duration_minutes(path)
    if duration_minutes is None:
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
            duration_minutes=duration_minutes,
        ),
    )


def convert_recovered_recording(
    recording: RecoveredRecording,
    converter: Callable[[Path, Path], None] = convert_wav_to_m4a,
    marker_writer: Callable[[Path, MeetingMeta], Path] = mark_audio_for_recovery,
) -> Path:
    if recording.ready_audio_path is not None:
        if not recording.ready_audio_path.is_file():
            raise FileNotFoundError(recording.ready_audio_path)
        return recording.ready_audio_path
    try:
        converter(recording.wav_path, recording.audio_path)
        marker_writer(recording.audio_path, recording.meta)
    except Exception:
        with suppress(OSError):
            recording.audio_path.unlink()
        raise
    with suppress(OSError):
        recording.wav_path.unlink()
    return recording.audio_path


def clear_audio_recovery_marker(audio_path: Path) -> None:
    with suppress(OSError):
        audio_path.with_suffix(".pending.json").unlink()


def _pending_recording_from_marker(marker: Path) -> RecoveredRecording | None:
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
        audio_path = marker.parent / str(payload["audio_file"])
        if (
            audio_path.parent != marker.parent
            or not audio_path.name.startswith(TEMP_RECORDING_PREFIX)
            or audio_path.suffix != ".m4a"
            or not audio_path.is_file()
            or audio_path.stat().st_size == 0
        ):
            return None
        meta = MeetingMeta(
            slug=str(payload["slug"]),
            started_at=datetime.fromisoformat(str(payload["started_at"])),
            calendar_title=str(payload["calendar_title"]),
            duration_minutes=int(payload.get("duration_minutes", 0)),
            speaker_candidates=tuple(str(item) for item in payload.get("speaker_candidates", ())),
        )
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return RecoveredRecording(
        wav_path=audio_path.with_suffix(".wav"),
        meta=meta,
        ready_audio_path=audio_path,
        marker_path=marker,
    )


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


def _duration_minutes(path: Path) -> int | None:
    try:
        with wave.open(str(path), "rb") as audio_file:
            frames = audio_file.getnframes()
            rate = audio_file.getframerate()
            bytes_per_frame = audio_file.getnchannels() * audio_file.getsampwidth()
            first_frame = audio_file.readframes(1)
    except (OSError, EOFError, wave.Error):
        return None
    if frames <= 0 or rate <= 0 or bytes_per_frame <= 0:
        return None
    if len(first_frame) < bytes_per_frame:
        return None
    return max(0, round(frames / rate / 60))

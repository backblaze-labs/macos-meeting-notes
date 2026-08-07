"""Native meeting-audio mode definitions and selection."""

from __future__ import annotations

from dataclasses import dataclass

from meeting_memory.service.recorder import RecorderService


@dataclass(frozen=True)
class AudioMode:
    key: str
    label: str
    capture_system_audio: bool
    capture_microphone: bool
    monitor_audio: bool
    description: str


FULL_MEETING = AudioMode(
    key="full-meeting",
    label="Full Meeting",
    capture_system_audio=True,
    capture_microphone=True,
    monitor_audio=True,
    description="record system audio and the current macOS microphone while listening normally",
)

SILENT_SYSTEM_ONLY = AudioMode(
    key="silent-system-only",
    label="Silent System Only",
    capture_system_audio=True,
    capture_microphone=False,
    monitor_audio=False,
    description="record system audio with microphone off and playback muted",
)

AUDIO_MODES = (FULL_MEETING, SILENT_SYSTEM_ONLY)


def apply_audio_mode(
    mode: AudioMode,
    recorder: RecorderService,
) -> None:
    if recorder.is_recording:
        raise RuntimeError("Stop the current recording before changing audio mode.")
    recorder.capture_mode = mode.key


def audio_mode_by_key(key: str) -> AudioMode:
    for mode in AUDIO_MODES:
        if mode.key == key:
            return mode
    raise LookupError(f"Audio mode not found: {key}")

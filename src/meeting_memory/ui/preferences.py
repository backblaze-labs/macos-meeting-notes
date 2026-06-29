"""Minimal preferences editor."""

from __future__ import annotations

import json
from pathlib import Path

from meeting_memory.config.settings import Settings
from meeting_memory.types.speakers import KnownSpeaker
from meeting_memory.ui.preference_forms import (
    PreferenceFormField,
    open_known_speakers_form,
    open_preferences_form,
)

PREFERENCE_KEYS = (
    "MEETINGS_DIR",
    "NOTIFY_MINUTES_BEFORE",
    "MAX_RECORDING_MINUTES",
    "AUDIO_DEVICE",
)
KNOWN_SPEAKERS_KEY = "KNOWN_SPEAKERS"
ENV_UPDATE_ORDER = (*PREFERENCE_KEYS, KNOWN_SPEAKERS_KEY)
PREFERENCE_LABELS = {
    "MEETINGS_DIR": "Meetings folder",
    "NOTIFY_MINUTES_BEFORE": "Reminder (minutes)",
    "MAX_RECORDING_MINUTES": "Recording limit (minutes)",
    "AUDIO_DEVICE": "Audio device",
}
PREFERENCE_GUIDANCE = {
    "MEETINGS_DIR": "Where recordings, transcripts, and notes are saved.",
    "NOTIFY_MINUTES_BEFORE": "How early to remind you before Calendar meetings.",
    "MAX_RECORDING_MINUTES": (
        "Maximum recording length before the app stops automatically."
    ),
    "AUDIO_DEVICE": "Which macOS input to record from.",
}
KNOWN_SPEAKERS_GUIDANCE = (
    "This cleans up Calendar speaker suggestions. "
    "Alias is the name to show; match is an invite email, email username, or Calendar name."
)


def preferences_text(settings: Settings) -> str:
    lines: list[str] = []
    for field in _preference_fields(settings):
        lines.extend(
            [
                f"# {field.label} ({field.key})",
                f"# {field.guidance}",
                f"{field.key}={field.value}",
                "",
            ]
        )
    return "\n".join(lines).rstrip()


def parse_preferences_text(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key in PREFERENCE_KEYS:
            values[key] = value.strip()
    return values


def known_speakers_text(settings: Settings) -> str:
    return render_known_speakers(settings.known_speakers)


def render_known_speakers(speakers: tuple[KnownSpeaker, ...]) -> str:
    lines: list[str] = []
    for speaker in speakers:
        if speaker.matches:
            lines.append(f"{speaker.name} | {', '.join(speaker.matches)}")
        else:
            lines.append(f"{speaker.name} |")
    return "\n".join(lines)


def parse_known_speakers_text(text: str) -> tuple[KnownSpeaker, ...]:
    value = text.strip()
    if not value:
        return ()
    if value[:1] in ("{", "["):
        return Settings.parse_known_speakers(value)

    speakers: list[KnownSpeaker] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        speakers.extend(_parse_known_speaker_line(line))
    return _dedupe_known_speakers(speakers)


def known_speakers_env_value(speakers: tuple[KnownSpeaker, ...]) -> str:
    return json.dumps(
        {speaker.name: list(speaker.matches) for speaker in speakers},
        separators=(",", ":"),
    )


def update_env_file(env_path: Path, updates: dict[str, str]) -> None:
    existing = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    seen: set[str] = set()
    new_lines: list[str] = []

    for line in existing:
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key in updates:
            new_lines.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            new_lines.append(line)

    for key in ENV_UPDATE_ORDER:
        if key in updates and key not in seen:
            new_lines.append(f"{key}={updates[key]}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def open_known_speakers_window(settings: Settings, env_path: Path = Path(".env")) -> bool:
    try:
        speakers = open_known_speakers_form(settings.known_speakers)
    except Exception:
        speakers = _prompt_known_speakers_text(settings)
    if speakers is None:
        return False

    update_env_file(env_path, {KNOWN_SPEAKERS_KEY: known_speakers_env_value(speakers)})
    _load_rumps().alert("Known speakers saved. Restart Meeting Memory to apply changes.")
    return True


def open_preferences_window(settings: Settings, env_path: Path = Path(".env")) -> bool:
    try:
        updates = open_preferences_form(_preference_fields(settings))
    except Exception:
        updates = _prompt_preferences_text(settings)
    if updates is None:
        return False

    update_env_file(env_path, updates)
    _load_rumps().alert("Preferences saved. Restart Meeting Memory to apply changes.")
    return True


def _prompt_known_speakers_text(settings: Settings) -> tuple[KnownSpeaker, ...] | None:
    rumps = _load_rumps()
    window = rumps.Window(
        message=(
            f"{KNOWN_SPEAKERS_GUIDANCE}\n"
            "Fallback format: one row per person as Alias | calendar match 1, match 2."
        ),
        title="Known Speakers",
        default_text=known_speakers_text(settings),
        ok="Save",
        cancel=True,
        dimensions=(560, 240),
    )
    response = window.run()
    if not getattr(response, "clicked", False):
        return None

    return parse_known_speakers_text(response.text)


def _prompt_preferences_text(settings: Settings) -> dict[str, str] | None:
    rumps = _load_rumps()
    window = rumps.Window(
        message="Fallback editor. Comments explain each field and show a safe example.",
        title="Meeting Memory Preferences",
        default_text=preferences_text(settings),
        ok="Save",
        cancel=True,
        dimensions=(640, 320),
    )
    response = window.run()
    if not getattr(response, "clicked", False):
        return None

    return parse_preferences_text(response.text)


def _load_rumps():
    import rumps

    return rumps


def _parse_known_speaker_line(line: str) -> tuple[KnownSpeaker, ...]:
    if _looks_like_legacy_csv(line):
        return Settings.parse_known_speakers(line)

    name, raw_matches = _split_known_speaker_line(line)
    return (KnownSpeaker(name, _split_matches(raw_matches)),) if name else ()


def _looks_like_legacy_csv(line: str) -> bool:
    return ":" not in line and line.count("=") > 1


def _split_known_speaker_line(line: str) -> tuple[str, str]:
    for separator in (":", "=", "|"):
        if separator in line:
            name, raw_matches = line.split(separator, 1)
            return name.strip(), raw_matches.strip()
    return line.strip(), ""


def _split_matches(raw_matches: str) -> tuple[str, ...]:
    return tuple(match.strip() for match in raw_matches.split(",") if match.strip())


def _dedupe_known_speakers(speakers: list[KnownSpeaker]) -> tuple[KnownSpeaker, ...]:
    deduped: list[KnownSpeaker] = []
    seen: set[str] = set()
    for speaker in speakers:
        key = speaker.name.casefold()
        if key not in seen:
            deduped.append(speaker)
            seen.add(key)
    return tuple(deduped)


def _preference_fields(settings: Settings) -> tuple[PreferenceFormField, ...]:
    values = {
        "MEETINGS_DIR": str(settings.meetings_dir),
        "NOTIFY_MINUTES_BEFORE": str(settings.notify_minutes_before),
        "MAX_RECORDING_MINUTES": str(settings.max_recording_minutes),
        "AUDIO_DEVICE": settings.audio_device,
    }
    return tuple(
        PreferenceFormField(
            key=key,
            label=PREFERENCE_LABELS[key],
            value=values[key],
            guidance=PREFERENCE_GUIDANCE[key],
        )
        for key in PREFERENCE_KEYS
    )

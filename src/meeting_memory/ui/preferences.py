"""Minimal preferences editor."""

from __future__ import annotations

import json
from pathlib import Path

from meeting_memory.config.settings import Settings
from meeting_memory.types.speakers import KnownSpeaker

PREFERENCE_KEYS = (
    "MEETINGS_DIR",
    "NOTIFY_MINUTES_BEFORE",
    "MAX_RECORDING_MINUTES",
    "AUDIO_DEVICE",
)
KNOWN_SPEAKERS_KEY = "KNOWN_SPEAKERS"
ENV_UPDATE_ORDER = (*PREFERENCE_KEYS, KNOWN_SPEAKERS_KEY)


def preferences_text(settings: Settings) -> str:
    return "\n".join(
        [
            f"MEETINGS_DIR={settings.meetings_dir}",
            f"NOTIFY_MINUTES_BEFORE={settings.notify_minutes_before}",
            f"MAX_RECORDING_MINUTES={settings.max_recording_minutes}",
            f"AUDIO_DEVICE={settings.audio_device}",
        ]
    )


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
            lines.append(f"{speaker.name}: {', '.join(speaker.matches)}")
        else:
            lines.append(speaker.name)
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
    rumps = _load_rumps()
    window = rumps.Window(
        message="One speaker per line: Display Name: email, calendar-name, email-local-part",
        title="Known Speakers",
        default_text=known_speakers_text(settings),
        ok="Save",
        cancel=True,
        dimensions=(560, 240),
    )
    response = window.run()
    if not getattr(response, "clicked", False):
        return False

    speakers = parse_known_speakers_text(response.text)
    update_env_file(env_path, {KNOWN_SPEAKERS_KEY: known_speakers_env_value(speakers)})
    rumps.alert("Known speakers saved. Restart Meeting Memory to apply changes.")
    return True


def open_preferences_window(settings: Settings, env_path: Path = Path(".env")) -> bool:
    rumps = _load_rumps()
    window = rumps.Window(
        message="Edit values, then restart Meeting Memory.",
        title="Meeting Memory Preferences",
        default_text=preferences_text(settings),
        ok="Save",
        cancel=True,
        dimensions=(480, 180),
    )
    response = window.run()
    if not getattr(response, "clicked", False):
        return False

    update_env_file(env_path, parse_preferences_text(response.text))
    rumps.alert("Preferences saved. Restart Meeting Memory to apply changes.")
    return True


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
    for separator in (":", "="):
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

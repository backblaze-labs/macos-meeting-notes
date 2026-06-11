"""Minimal preferences editor."""

from __future__ import annotations

from pathlib import Path

from meeting_memory.config.settings import Settings

PREFERENCE_KEYS = (
    "MEETINGS_DIR",
    "NOTIFY_MINUTES_BEFORE",
    "MAX_RECORDING_MINUTES",
    "AUDIO_DEVICE",
)


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

    for key in PREFERENCE_KEYS:
        if key in updates and key not in seen:
            new_lines.append(f"{key}={updates[key]}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


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

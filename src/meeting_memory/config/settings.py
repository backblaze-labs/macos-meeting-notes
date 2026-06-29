"""Environment-backed settings and fail-fast validation."""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from meeting_memory.config.defaults import (
    DEFAULT_ANTHROPIC_MODEL,
    DEFAULT_AUDIO_DEVICE,
    DEFAULT_CALENDAR_POLL_INTERVAL,
    DEFAULT_GOOGLE_CALENDAR_CREDENTIALS_FILE,
    DEFAULT_GOOGLE_CALENDAR_ID,
    DEFAULT_KNOWN_SPEAKERS,
    DEFAULT_MAX_RECORDING_MINUTES,
    DEFAULT_MEETINGS_DIR,
    DEFAULT_NOTIFY_MINUTES_BEFORE,
    DEFAULT_SUMMARY_PROMPT_FILE,
    PLACEHOLDER_MARKERS,
)
from meeting_memory.types.speakers import KnownSpeaker

KNOWN_SPEAKER_LEGACY_MATCH_SEPARATORS = re.compile(r"[|;]")


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables or `.env`."""

    b2_application_key_id: str
    b2_application_key: str
    b2_endpoint: str
    b2_region: str
    b2_bucket_name: str
    assemblyai_api_key: str

    anthropic_api_key: str | None = None
    anthropic_model: str = DEFAULT_ANTHROPIC_MODEL
    summary_prompt_file: Path | None = Path(DEFAULT_SUMMARY_PROMPT_FILE)
    google_calendar_credentials_file: Path = Path(DEFAULT_GOOGLE_CALENDAR_CREDENTIALS_FILE)
    google_calendar_id: str = DEFAULT_GOOGLE_CALENDAR_ID
    known_speakers: tuple[KnownSpeaker, ...] = DEFAULT_KNOWN_SPEAKERS
    meetings_dir: Path = Path(DEFAULT_MEETINGS_DIR)
    audio_device: str = DEFAULT_AUDIO_DEVICE
    notify_minutes_before: int = Field(default=DEFAULT_NOTIFY_MINUTES_BEFORE, gt=0)
    max_recording_minutes: int = Field(default=DEFAULT_MAX_RECORDING_MINUTES, gt=0)
    calendar_poll_interval: int = Field(default=DEFAULT_CALENDAR_POLL_INTERVAL, gt=0)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        enable_decoding=False,
    )

    @field_validator(
        "b2_application_key_id",
        "b2_application_key",
        "b2_endpoint",
        "b2_region",
        "b2_bucket_name",
        "assemblyai_api_key",
        mode="before",
    )
    @classmethod
    def reject_required_placeholders(cls, value: Any) -> str:
        text = str(value or "").strip()
        if looks_placeholder(text):
            raise ValueError("must be set to a non-placeholder value")
        return text

    @field_validator("anthropic_api_key", mode="before")
    @classmethod
    def blank_optional_secret_to_none(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator("summary_prompt_file", mode="before")
    @classmethod
    def blank_optional_path_to_none(cls, value: Any) -> Path | None:
        if value is None:
            return None
        text = str(value).strip()
        return Path(text) if text else None

    @field_validator("anthropic_model", "google_calendar_id", "audio_device", mode="before")
    @classmethod
    def reject_blank_defaults(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("must not be blank")
        return text

    @field_validator("known_speakers", mode="before")
    @classmethod
    def parse_known_speakers(cls, value: Any) -> tuple[KnownSpeaker, ...]:
        if value is None:
            return DEFAULT_KNOWN_SPEAKERS
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return DEFAULT_KNOWN_SPEAKERS
            if text[:1] in ("{", "["):
                try:
                    return cls._known_speakers_from_value(json.loads(text))
                except json.JSONDecodeError as exc:
                    raise ValueError("must be valid JSON") from exc
            return cls._known_speakers_from_value(text.split(","))
        return cls._known_speakers_from_value(value)

    @classmethod
    def _known_speakers_from_value(cls, value: Any) -> tuple[KnownSpeaker, ...]:
        if isinstance(value, KnownSpeaker):
            return (value,)
        if isinstance(value, Mapping):
            return cls._dedupe_known_speakers(
                KnownSpeaker(str(name), cls._known_speaker_matches(matches))
                for name, matches in value.items()
            )
        if isinstance(value, Iterable) and not isinstance(value, (bytes, str)):
            speakers = [
                speaker
                for item in value
                if (speaker := cls._known_speaker_from_item(item)) is not None
            ]
            return cls._dedupe_known_speakers(speakers)
        raise ValueError("must be a JSON object mapping speaker names to match lists")

    @classmethod
    def _known_speaker_from_item(cls, value: Any) -> KnownSpeaker | None:
        if isinstance(value, KnownSpeaker):
            return value
        if isinstance(value, Mapping):
            name = value.get("name")
            if name is None:
                raise ValueError("known speaker objects must include a name")
            matches = value.get("matches", value.get("aliases", value.get("emails", ())))
            return KnownSpeaker(str(name), cls._known_speaker_matches(matches))
        display, matches = cls._split_legacy_known_speaker(str(value))
        return KnownSpeaker(display, matches) if display else None

    @classmethod
    def _known_speaker_matches(cls, value: Any) -> tuple[str, ...]:
        if value is None:
            return ()
        if isinstance(value, str):
            text = value.strip()
            return (text,) if text else ()
        if isinstance(value, Mapping):
            matches: list[str] = []
            for key in ("matches", "aliases", "emails"):
                matches.extend(cls._known_speaker_matches(value.get(key)))
            return tuple(dict.fromkeys(matches))
        if isinstance(value, Iterable) and not isinstance(value, bytes):
            matches = [text for item in value if (text := str(item).strip())]
            return tuple(dict.fromkeys(matches))
        text = str(value).strip()
        return (text,) if text else ()

    @classmethod
    def _split_legacy_known_speaker(cls, raw_alias: str) -> tuple[str, tuple[str, ...]]:
        value = raw_alias.strip()
        if not value:
            return "", ()

        name, separator, raw_matches = value.partition("=")
        matches = cls._split_legacy_matches(raw_matches) if separator else ()
        if not matches:
            match = re.fullmatch(r"(.+?)\s*<([^>]+)>", name.strip())
            if match:
                return match.group(1).strip(), (match.group(2).strip(),)
        return name.strip(), matches

    @staticmethod
    def _split_legacy_matches(raw_matches: str) -> tuple[str, ...]:
        return tuple(
            value.strip()
            for value in KNOWN_SPEAKER_LEGACY_MATCH_SEPARATORS.split(raw_matches)
            if value.strip()
        )

    @staticmethod
    def _dedupe_known_speakers(
        speakers: Iterable[KnownSpeaker],
    ) -> tuple[KnownSpeaker, ...]:
        deduped: list[KnownSpeaker] = []
        seen: set[str] = set()
        for speaker in speakers:
            key = speaker.name.casefold()
            if key not in seen:
                deduped.append(speaker)
                seen.add(key)
        return tuple(deduped)

    @property
    def meetings_dir_path(self) -> Path:
        return self.meetings_dir.expanduser()

    @property
    def google_credentials_path(self) -> Path:
        return self.google_calendar_credentials_file.expanduser()

    @property
    def summary_prompt_path(self) -> Path | None:
        if self.summary_prompt_file is None:
            return None
        return self.summary_prompt_file.expanduser()


class GoogleAuthSettings(BaseSettings):
    """Minimal settings required for the one-time Google OAuth flow."""

    google_calendar_credentials_file: Path = Path(DEFAULT_GOOGLE_CALENDAR_CREDENTIALS_FILE)
    google_calendar_id: str = DEFAULT_GOOGLE_CALENDAR_ID
    known_speakers: tuple[KnownSpeaker, ...] = DEFAULT_KNOWN_SPEAKERS

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        enable_decoding=False,
    )

    @field_validator("google_calendar_id", mode="before")
    @classmethod
    def reject_blank_calendar_id(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("must not be blank")
        return text

    @field_validator("known_speakers", mode="before")
    @classmethod
    def parse_known_speakers(cls, value: Any) -> tuple[KnownSpeaker, ...]:
        return Settings.parse_known_speakers(value)

    @property
    def google_credentials_path(self) -> Path:
        return self.google_calendar_credentials_file.expanduser()


def looks_placeholder(value: str) -> bool:
    normalized = value.strip().lower()
    return not normalized or any(marker in normalized for marker in PLACEHOLDER_MARKERS)


def load_settings(env_file: str | Path | None = ".env") -> Settings:
    return Settings(_env_file=env_file)


def load_google_auth_settings(env_file: str | Path | None = ".env") -> GoogleAuthSettings:
    return GoogleAuthSettings(_env_file=env_file)


def format_settings_error(error: ValidationError) -> str:
    lines = ["Configuration is invalid:"]
    for item in error.errors():
        field = ".".join(str(part) for part in item["loc"])
        lines.append(f"- {field}: {item['msg']}")
    lines.append("Fix the values in .env or the process environment.")
    return "\n".join(lines) + "\n"


def validate_or_exit(env_file: str | Path | None = ".env") -> Settings:
    try:
        return load_settings(env_file)
    except ValidationError as exc:
        sys.stderr.write(format_settings_error(exc))
        raise SystemExit(2) from exc

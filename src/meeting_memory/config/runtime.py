"""Capability-scoped runtime configuration for the local-first app."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import Field, PrivateAttr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from meeting_memory.config.defaults import (
    DEFAULT_ANTHROPIC_MODEL,
    DEFAULT_CALENDAR_POLL_INTERVAL,
    DEFAULT_GOOGLE_CALENDAR_ID,
    DEFAULT_KNOWN_SPEAKERS,
    DEFAULT_MAX_RECORDING_MINUTES,
    DEFAULT_MEETINGS_DIR,
    DEFAULT_NOTIFY_MINUTES_BEFORE,
    DEFAULT_SUMMARY_PROMPT_FILE,
)
from meeting_memory.config.settings import Settings, looks_placeholder
from meeting_memory.types.speakers import KnownSpeaker


@dataclass(frozen=True, slots=True)
class TranscriptionConfig:
    api_key: str


@dataclass(frozen=True, slots=True)
class BackupConfig:
    application_key_id: str
    application_key: str
    endpoint: str
    region: str
    bucket_name: str


@dataclass(frozen=True, slots=True)
class CalendarConfig:
    credentials_file: Path
    calendar_id: str
    notify_minutes_before: int
    poll_interval: int


@dataclass(frozen=True, slots=True)
class NotesConfig:
    api_key: str
    model: str
    prompt_file: Path | None


class RuntimeSettings(BaseSettings):
    """Core settings plus independently optional provider groups."""

    meetings_dir: Path = Path(DEFAULT_MEETINGS_DIR)
    known_speakers: tuple[KnownSpeaker, ...] = DEFAULT_KNOWN_SPEAKERS
    notify_minutes_before: int | None = DEFAULT_NOTIFY_MINUTES_BEFORE
    max_recording_minutes: int = Field(default=DEFAULT_MAX_RECORDING_MINUTES, gt=0)
    calendar_poll_interval: int | None = DEFAULT_CALENDAR_POLL_INTERVAL

    assemblyai_api_key: str | None = None
    b2_application_key_id: str | None = None
    b2_application_key: str | None = None
    b2_endpoint: str | None = None
    b2_region: str | None = None
    b2_bucket_name: str | None = None
    google_calendar_credentials_file: Path | None = None
    google_calendar_id: str | None = DEFAULT_GOOGLE_CALENDAR_ID
    anthropic_api_key: str | None = None
    anthropic_model: str | None = DEFAULT_ANTHROPIC_MODEL
    summary_prompt_file: Path | None = Path(DEFAULT_SUMMARY_PROMPT_FILE)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        enable_decoding=False,
    )
    _meetings_dir_path: Path = PrivateAttr()

    def model_post_init(self, _context: Any) -> None:
        self._meetings_dir_path = self.meetings_dir.expanduser().resolve(strict=False)

    @field_validator(
        "assemblyai_api_key",
        "b2_application_key_id",
        "b2_application_key",
        "b2_endpoint",
        "b2_region",
        "b2_bucket_name",
        "anthropic_api_key",
        mode="before",
    )
    @classmethod
    def optional_text(cls, value: Any) -> str | None:
        text = str(value or "").strip()
        return None if not text or looks_placeholder(text) else text

    @field_validator("google_calendar_credentials_file", "summary_prompt_file", mode="before")
    @classmethod
    def optional_path(cls, value: Any) -> Path | None:
        text = str(value or "").strip()
        return Path(text) if text and not looks_placeholder(text) else None

    @field_validator("known_speakers", mode="before")
    @classmethod
    def parse_known_speakers(cls, value: Any) -> tuple[KnownSpeaker, ...]:
        try:
            return Settings.parse_known_speakers(value)
        except (TypeError, ValueError):
            return DEFAULT_KNOWN_SPEAKERS

    @field_validator("google_calendar_id", "anthropic_model", mode="before")
    @classmethod
    def optional_name(cls, value: Any) -> str | None:
        text = str(value or "").strip()
        return text or None

    @field_validator("notify_minutes_before", "calendar_poll_interval", mode="before")
    @classmethod
    def optional_calendar_integer(cls, value: Any, info) -> int | None:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        if info.field_name == "notify_minutes_before":
            return parsed if parsed >= 0 else None
        return parsed if parsed > 0 else None

    @property
    def meetings_dir_path(self) -> Path:
        return self._meetings_dir_path

    @property
    def summary_prompt_path(self) -> Path | None:
        """Compatibility boundary used by the native Notes prompt editor."""

        return self.summary_prompt_file.expanduser() if self.summary_prompt_file else None

    @property
    def transcription(self) -> TranscriptionConfig | None:
        return TranscriptionConfig(self.assemblyai_api_key) if self.assemblyai_api_key else None

    @property
    def backup(self) -> BackupConfig | None:
        values = (
            self.b2_application_key_id,
            self.b2_application_key,
            self.b2_endpoint,
            self.b2_region,
            self.b2_bucket_name,
        )
        if not all(values):
            return None
        return BackupConfig(*values)  # type: ignore[arg-type]

    @property
    def calendar(self) -> CalendarConfig | None:
        if (
            self.google_calendar_credentials_file is None
            or not self.google_calendar_id
            or self.notify_minutes_before is None
            or self.calendar_poll_interval is None
        ):
            return None
        return CalendarConfig(
            self.google_calendar_credentials_file.expanduser(),
            self.google_calendar_id,
            self.notify_minutes_before,
            self.calendar_poll_interval,
        )

    @property
    def notes(self) -> NotesConfig | None:
        if self.anthropic_api_key is None or not self.anthropic_model:
            return None
        prompt = self.summary_prompt_file.expanduser() if self.summary_prompt_file else None
        return NotesConfig(self.anthropic_api_key, self.anthropic_model, prompt)


def load_runtime_settings(env_file: str | Path | None = ".env") -> RuntimeSettings:
    return RuntimeSettings(_env_file=env_file)

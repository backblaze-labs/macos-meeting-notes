"""Typed setting schema for progressive configuration composition."""

from __future__ import annotations

from dataclasses import dataclass

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
from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration import SECRET_KEYS, SecretId, SettingKey


@dataclass(frozen=True, slots=True)
class SettingDefinition:
    """One recognized setting and its capability/default behavior."""

    key: SettingKey
    capability: Capability
    default: object = None
    required_to_enable: bool = False

    @property
    def secret(self) -> bool:
        return self.key in SECRET_KEYS


SETTING_DEFINITIONS = (
    SettingDefinition(
        SettingKey.MEETINGS_DIR,
        Capability.RECORDING_CORE,
        DEFAULT_MEETINGS_DIR,
    ),
    SettingDefinition(
        SettingKey.MAX_RECORDING_MINUTES,
        Capability.RECORDING_CORE,
        DEFAULT_MAX_RECORDING_MINUTES,
    ),
    SettingDefinition(
        SettingKey.ASSEMBLYAI_API_KEY,
        Capability.TRANSCRIPTION,
        required_to_enable=True,
    ),
    SettingDefinition(
        SettingKey.B2_APPLICATION_KEY_ID,
        Capability.BACKUP,
        required_to_enable=True,
    ),
    SettingDefinition(
        SettingKey.B2_APPLICATION_KEY,
        Capability.BACKUP,
        required_to_enable=True,
    ),
    SettingDefinition(SettingKey.B2_ENDPOINT, Capability.BACKUP, required_to_enable=True),
    SettingDefinition(SettingKey.B2_REGION, Capability.BACKUP, required_to_enable=True),
    SettingDefinition(
        SettingKey.B2_BUCKET_NAME,
        Capability.BACKUP,
        required_to_enable=True,
    ),
    SettingDefinition(
        SettingKey.GOOGLE_CALENDAR_CREDENTIALS_FILE,
        Capability.CALENDAR,
        required_to_enable=True,
    ),
    SettingDefinition(
        SettingKey.GOOGLE_CALENDAR_ID,
        Capability.CALENDAR,
        DEFAULT_GOOGLE_CALENDAR_ID,
    ),
    SettingDefinition(
        SettingKey.KNOWN_SPEAKERS,
        Capability.CALENDAR,
        DEFAULT_KNOWN_SPEAKERS,
    ),
    SettingDefinition(
        SettingKey.NOTIFY_MINUTES_BEFORE,
        Capability.CALENDAR,
        DEFAULT_NOTIFY_MINUTES_BEFORE,
    ),
    SettingDefinition(
        SettingKey.CALENDAR_POLL_INTERVAL,
        Capability.CALENDAR,
        DEFAULT_CALENDAR_POLL_INTERVAL,
    ),
    SettingDefinition(
        SettingKey.ANTHROPIC_API_KEY,
        Capability.NOTES,
        required_to_enable=True,
    ),
    SettingDefinition(
        SettingKey.ANTHROPIC_MODEL,
        Capability.NOTES,
        DEFAULT_ANTHROPIC_MODEL,
    ),
    SettingDefinition(
        SettingKey.SUMMARY_PROMPT_FILE,
        Capability.NOTES,
        DEFAULT_SUMMARY_PROMPT_FILE,
    ),
)


def definitions_for(capability: Capability) -> tuple[SettingDefinition, ...]:
    return tuple(
        definition for definition in SETTING_DEFINITIONS if definition.capability is capability
    )


def required_keys(capability: Capability) -> tuple[SettingKey, ...]:
    return tuple(
        definition.key
        for definition in definitions_for(capability)
        if definition.required_to_enable
    )


def secret_id_for(key: SettingKey) -> SecretId | None:
    return {
        SettingKey.ASSEMBLYAI_API_KEY: SecretId.TRANSCRIPTION,
        SettingKey.B2_APPLICATION_KEY_ID: SecretId.BACKUP,
        SettingKey.B2_APPLICATION_KEY: SecretId.BACKUP,
        SettingKey.ANTHROPIC_API_KEY: SecretId.NOTES,
    }.get(key)

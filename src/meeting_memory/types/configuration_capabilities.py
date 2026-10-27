"""Capability ownership of recognized configuration fields."""

from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration import SettingKey

SETTING_CAPABILITY = {
    SettingKey.MEETINGS_DIR: Capability.RECORDING_CORE,
    SettingKey.MAX_RECORDING_MINUTES: Capability.RECORDING_CORE,
    SettingKey.TRANSCRIPTION_PROVIDER: Capability.TRANSCRIPTION,
    SettingKey.ASSEMBLYAI_CONSENT: Capability.TRANSCRIPTION,
    SettingKey.ASSEMBLYAI_API_KEY: Capability.TRANSCRIPTION,
    SettingKey.B2_APPLICATION_KEY_ID: Capability.BACKUP,
    SettingKey.B2_APPLICATION_KEY: Capability.BACKUP,
    SettingKey.B2_ENDPOINT: Capability.BACKUP,
    SettingKey.B2_REGION: Capability.BACKUP,
    SettingKey.B2_BUCKET_NAME: Capability.BACKUP,
    SettingKey.GOOGLE_CALENDAR_CREDENTIALS_FILE: Capability.CALENDAR,
    SettingKey.GOOGLE_CALENDAR_ID: Capability.CALENDAR,
    SettingKey.KNOWN_SPEAKERS: Capability.CALENDAR,
    SettingKey.NOTIFY_MINUTES_BEFORE: Capability.CALENDAR,
    SettingKey.CALENDAR_POLL_INTERVAL: Capability.CALENDAR,
    SettingKey.ANTHROPIC_API_KEY: Capability.NOTES,
    SettingKey.ANTHROPIC_MODEL: Capability.NOTES,
    SettingKey.SUMMARY_PROMPT_FILE: Capability.NOTES,
}

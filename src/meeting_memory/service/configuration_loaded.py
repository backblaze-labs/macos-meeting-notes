"""Redacted effective configuration accessors shared by active consumers."""

from __future__ import annotations

from pathlib import Path

from meeting_memory.config.runtime import (
    BackupConfig,
    CalendarAuthConfig,
    CalendarConfig,
    NotesConfig,
    RuntimeSettings,
    TranscriptionConfig,
)
from meeting_memory.config.schema import SETTING_DEFINITIONS
from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration import SettingKey
from meeting_memory.types.configuration_resolution import (
    ConfigurationIssue,
    ConfigurationUse,
    ScopedConfigurationResolution,
    SettingSource,
)


class LoadedConfiguration:
    """One scoped effective snapshot; raw settings stay out of representations."""

    __slots__ = ("_use", "_settings", "_resolution", "_issues")

    def __init__(
        self,
        use: ConfigurationUse,
        settings: RuntimeSettings,
        resolution: ScopedConfigurationResolution,
        issues: tuple[ConfigurationIssue, ...] = (),
    ) -> None:
        object.__setattr__(self, "_use", use)
        object.__setattr__(self, "_settings", settings)
        object.__setattr__(self, "_resolution", resolution)
        object.__setattr__(self, "_issues", issues)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("loaded configuration is immutable")

    @property
    def use(self) -> ConfigurationUse:
        return self._use

    @property
    def settings(self) -> RuntimeSettings:
        return self._settings

    @property
    def resolution(self) -> ScopedConfigurationResolution:
        return self._resolution

    @property
    def issues(self) -> tuple[ConfigurationIssue, ...]:
        return self._issues

    def __repr__(self) -> str:
        return (
            f"LoadedConfiguration(use={self.use!r}, resolution={self.resolution!r}, "
            f"issues={self.issues!r}, settings=<redacted>)"
        )

    def capability_for(self, capability: Capability):
        return self.resolution.capability_for(capability)

    def capability_enabled(self, capability: Capability) -> bool:
        resolved = self.capability_for(capability)
        return resolved.enabled and not any(
            issue.capability is capability and issue.blocking for issue in self.issues
        )

    def process_environment_active(self, capability: Capability) -> bool:
        return self.capability_enabled(capability) and any(
            item.active
            and item.source is SettingSource.PROCESS_ENV
            and _capability_for(item.key) is capability
            for item in self.resolution.provenance
        )

    def process_environment_selected(self, capability: Capability) -> bool:
        self.capability_for(capability)
        return any(
            item.source is SettingSource.PROCESS_ENV and _capability_for(item.key) is capability
            for item in self.resolution.provenance
        )

    def value_for(self, key: SettingKey) -> object:
        value = self.resolution.value_for(key)
        capability = _capability_for(key)
        return value if self.capability_enabled(capability) else None

    @property
    def meetings_dir_path(self) -> Path:
        self.value_for(SettingKey.MEETINGS_DIR)
        return self.settings.meetings_dir_path

    @property
    def transcription(self) -> TranscriptionConfig | None:
        self.capability_for(Capability.TRANSCRIPTION)
        return (
            self.settings.transcription
            if self.capability_enabled(Capability.TRANSCRIPTION)
            else None
        )

    @property
    def backup(self) -> BackupConfig | None:
        self.capability_for(Capability.BACKUP)
        return self.settings.backup if self.capability_enabled(Capability.BACKUP) else None

    @property
    def calendar(self) -> CalendarConfig | None:
        self.capability_for(Capability.CALENDAR)
        return self.settings.calendar if self.capability_enabled(Capability.CALENDAR) else None

    @property
    def notes(self) -> NotesConfig | None:
        self.capability_for(Capability.NOTES)
        return self.settings.notes if self.capability_enabled(Capability.NOTES) else None

    @property
    def calendar_auth(self) -> CalendarAuthConfig | None:
        self.capability_for(Capability.CALENDAR)
        if not self.capability_enabled(Capability.CALENDAR):
            return None
        credentials = self.value_for(SettingKey.GOOGLE_CALENDAR_CREDENTIALS_FILE)
        calendar_id = self.value_for(SettingKey.GOOGLE_CALENDAR_ID)
        if credentials is None or not calendar_id:
            return None
        return CalendarAuthConfig(
            Path(str(credentials)).expanduser(),
            str(calendar_id),
            self.settings.known_speakers,
        )


def _capability_for(key: SettingKey) -> Capability:
    return next(item.capability for item in SETTING_DEFINITIONS if item.key is key)

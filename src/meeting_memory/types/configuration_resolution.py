"""Pure, diagnostic-safe configuration resolution boundary data."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration import SettingKey


class SettingSource(StrEnum):
    """Stable, value-free provenance names."""

    PROCESS_ENV = "process_env"
    APP_PREFERENCE = "app_preference"
    APP_KEYCHAIN = "app_keychain"
    LEGACY_ENV = "legacy_env"
    DEFAULT = "default"


@dataclass(frozen=True, slots=True)
class SettingProvenance:
    """Diagnostic-safe source metadata without a setting value."""

    key: SettingKey
    source: SettingSource
    active: bool = True


@dataclass(frozen=True, slots=True)
class CapabilityResolution:
    """Effective opt-in decision, including process override behavior."""

    capability: Capability
    preference: bool | None
    enabled: bool
    source: SettingSource
    process_override: bool = False
    configuration_error: bool = False


class ResolvedSetting:
    """Internal resolved value whose repr cannot disclose its content."""

    __slots__ = ("_provenance", "_value")

    def __init__(self, provenance: SettingProvenance, value: object) -> None:
        object.__setattr__(self, "_provenance", provenance)
        object.__setattr__(self, "_value", value)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("ResolvedSetting is immutable")

    def __deepcopy__(self, _memo):
        return self

    @property
    def provenance(self) -> SettingProvenance:
        return self._provenance

    @property
    def value(self) -> object:
        return self._value

    def __repr__(self) -> str:
        return f"ResolvedSetting(provenance={self.provenance!r}, value=<redacted>)"


@dataclass(frozen=True, slots=True)
class ConfigurationResolution:
    """Pure resolver result with separately safe provenance."""

    settings: tuple[ResolvedSetting, ...]
    capabilities: tuple[CapabilityResolution, ...]

    def __post_init__(self) -> None:
        setting_by_key = {item.provenance.key: item for item in self.settings}
        capability_by_id = {item.capability: item for item in self.capabilities}
        if len(setting_by_key) != len(self.settings) or set(setting_by_key) != set(SettingKey):
            raise ValueError("configuration resolution requires every setting exactly once")
        if (
            len(capability_by_id) != len(self.capabilities)
            or set(capability_by_id) != set(Capability)
        ):
            raise ValueError("configuration resolution requires every capability exactly once")
        object.__setattr__(
            self,
            "settings",
            tuple(setting_by_key[key] for key in SettingKey),
        )
        object.__setattr__(
            self,
            "capabilities",
            tuple(capability_by_id[capability] for capability in Capability),
        )

    @property
    def provenance(self) -> tuple[SettingProvenance, ...]:
        return tuple(setting.provenance for setting in self.settings)

    def value_for(self, key: SettingKey) -> object:
        return next(
            setting.value
            for setting in self.settings
            if setting.provenance.key is key
        )

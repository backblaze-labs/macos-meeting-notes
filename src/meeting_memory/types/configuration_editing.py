"""Redacted boundaries for explicit native configuration editing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration import SECRET_KEYS, SecretBundle, SecretId, SettingKey

_OPAQUE_ID = re.compile(r"[0-9a-f]{32}")
_SETTING_CAPABILITY = {
    SettingKey.MEETINGS_DIR: Capability.RECORDING_CORE,
    SettingKey.MAX_RECORDING_MINUTES: Capability.RECORDING_CORE,
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
_CAPABILITY_SECRET = {
    Capability.TRANSCRIPTION: SecretId.TRANSCRIPTION,
    Capability.BACKUP: SecretId.BACKUP,
    Capability.NOTES: SecretId.NOTES,
}


class ConfigurationSaveState(StrEnum):
    SAVED = "saved"
    SAVED_CLEANUP_FAILED = "saved_cleanup_failed"
    SESSION_PAUSED = "session_paused"
    UNCHANGED = "unchanged"
    REJECTED = "rejected"
    PREFERENCES_CONFLICT = "preferences_conflict"
    KEYCHAIN_FAILED = "keychain_failed"
    DURABILITY_UNCERTAIN = "durability_uncertain"
    ACTIVATION_UNCERTAIN = "activation_uncertain"
    CLEANUP_FAILED = "cleanup_failed"
    FAILED = "failed"


class SecretAvailability(StrEnum):
    NONE = "none"
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class OpaqueId:
    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        if not isinstance(value, str) or _OPAQUE_ID.fullmatch(value) is None:
            raise ValueError("identifier must be 32 lowercase hexadecimal characters")
        object.__setattr__(self, "_value", value)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("identifier is immutable")

    @property
    def value(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return f"{type(self).__name__}(<opaque>)"

    __str__ = __repr__

    def __eq__(self, other: object) -> bool:
        return type(other) is type(self) and self.value == other.value

    def __hash__(self) -> int:
        return hash((type(self), self.value))

    def __deepcopy__(self, _memo):
        return self


class ConfigurationEditId(OpaqueId):
    pass


class ConfigurationOperationId(OpaqueId):
    pass


class ConfigurationValue:
    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        if not isinstance(value, str):
            raise ValueError("configuration form values must be text")
        object.__setattr__(self, "_value", value)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("configuration values are immutable")

    @property
    def value(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "ConfigurationValue(<redacted>)"

    __str__ = __repr__

    def __deepcopy__(self, _memo):
        return self


@dataclass(frozen=True, slots=True)
class ConfigurationField:
    key: SettingKey
    value: ConfigurationValue

    def __post_init__(self) -> None:
        if not isinstance(self.key, SettingKey) or not isinstance(self.value, ConfigurationValue):
            raise ValueError("configuration fields require typed values")


@dataclass(frozen=True, slots=True)
class CapabilityConfiguration:
    edit_id: ConfigurationEditId
    capability: Capability
    preference: bool | None
    fields: tuple[ConfigurationField, ...]
    secret_availability: SecretAvailability
    legacy_active: bool
    process_present: bool
    process_reenables: bool
    legacy_reenables: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.edit_id, ConfigurationEditId) or not isinstance(
            self.capability, Capability
        ):
            raise ValueError("configuration view requires typed identifiers")
        if self.preference is not None and type(self.preference) is not bool:
            raise ValueError("configuration preference must be bool or None")
        if not isinstance(self.secret_availability, SecretAvailability):
            raise ValueError("configuration secret availability must be typed")
        if any(type(flag) is not bool for flag in self.flags):
            raise ValueError("configuration view flags must be boolean")
        object.__setattr__(self, "fields", _validated_fields(self.capability, self.fields))
        if self.capability is Capability.RECORDING_CORE and self.preference is not None:
            raise ValueError("Recording Core has no enablement preference")
        has_secret = self.capability in _CAPABILITY_SECRET
        if has_secret == (self.secret_availability is SecretAvailability.NONE):
            raise ValueError("secret availability does not match the capability")

    @property
    def flags(self) -> tuple[bool, ...]:
        return (
            self.legacy_active,
            self.process_present,
            self.process_reenables,
            self.legacy_reenables,
        )


class ConfigurationChange:
    __slots__ = ("edit_id", "capability", "enabled", "disclosure_confirmed", "_fields", "_secret")

    def __init__(
        self,
        edit_id: ConfigurationEditId,
        capability: Capability,
        enabled: bool | None,
        fields: tuple[ConfigurationField, ...],
        secret: SecretBundle | None = None,
        *,
        disclosure_confirmed: bool = False,
    ) -> None:
        if not isinstance(edit_id, ConfigurationEditId) or not isinstance(capability, Capability):
            raise ValueError("configuration change requires typed identifiers")
        if enabled is not None and type(enabled) is not bool:
            raise ValueError("configuration enabled must be bool or None")
        if type(disclosure_confirmed) is not bool:
            raise ValueError("disclosure confirmation must be boolean")
        fields = _validated_fields(capability, fields)
        expected_secret = _CAPABILITY_SECRET.get(capability)
        if secret is not None and (
            not isinstance(secret, SecretBundle) or secret.secret_id is not expected_secret
        ):
            raise ValueError("configuration secret does not match its capability")
        if capability is Capability.RECORDING_CORE:
            if enabled is not None or secret is not None:
                raise ValueError("Recording Core cannot be enabled or hold provider secrets")
        elif enabled is True and disclosure_confirmed is not True:
            raise ValueError("enabling an optional capability requires disclosure consent")
        object.__setattr__(self, "edit_id", edit_id)
        object.__setattr__(self, "capability", capability)
        object.__setattr__(self, "enabled", enabled)
        object.__setattr__(self, "disclosure_confirmed", disclosure_confirmed)
        object.__setattr__(self, "_fields", tuple(fields))
        object.__setattr__(self, "_secret", secret)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("configuration changes are immutable")

    @property
    def fields(self) -> tuple[ConfigurationField, ...]:
        return self._fields

    @property
    def secret(self) -> SecretBundle | None:
        return self._secret

    def __repr__(self) -> str:
        return (
            "ConfigurationChange("
            f"edit_id={self.edit_id!r}, capability={self.capability!r}, "
            f"enabled={self.enabled!r}, values=<redacted>)"
        )

    def __deepcopy__(self, _memo):
        return self


@dataclass(frozen=True, slots=True)
class ConfigurationSaveOutcome:
    state: ConfigurationSaveState
    capability: Capability
    summary: str
    action: str
    restart_required: bool = False
    pause_current_session: bool = False
    process_present: bool = False
    process_reenables: bool = False
    legacy_reenables: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.state, ConfigurationSaveState) or not isinstance(
            self.capability, Capability
        ):
            raise ValueError("configuration outcome requires typed state")
        if not self.summary.strip() or not self.action.strip():
            raise ValueError("configuration outcome requires safe text")
        if any(
            type(flag) is not bool
            for flag in (
                self.restart_required,
                self.pause_current_session,
                self.process_present,
                self.process_reenables,
                self.legacy_reenables,
            )
        ):
            raise ValueError("configuration outcome flags must be boolean")
        activated = self.state in {
            ConfigurationSaveState.SAVED,
            ConfigurationSaveState.SAVED_CLEANUP_FAILED,
            ConfigurationSaveState.DURABILITY_UNCERTAIN,
            ConfigurationSaveState.ACTIVATION_UNCERTAIN,
        }
        runtime_changed = activated or self.state is ConfigurationSaveState.SESSION_PAUSED
        if (self.restart_required or self.pause_current_session) and not runtime_changed:
            raise ValueError("failed or unchanged outcomes cannot change runtime state")
        if self.state is ConfigurationSaveState.SESSION_PAUSED and (
            self.restart_required
            or not self.pause_current_session
            or self.capability is Capability.RECORDING_CORE
            or not self.process_reenables
        ):
            raise ValueError("session-paused outcome is inconsistent")


def _validated_fields(
    capability: Capability,
    fields: tuple[ConfigurationField, ...],
) -> tuple[ConfigurationField, ...]:
    if not isinstance(fields, tuple) or not all(
        isinstance(field, ConfigurationField) for field in fields
    ):
        raise ValueError("configuration fields must be a typed tuple")
    keys = tuple(field.key for field in fields)
    expected = tuple(
        key
        for key in SettingKey
        if _SETTING_CAPABILITY[key] is capability and key not in SECRET_KEYS
    )
    if len(keys) != len(set(keys)) or set(keys) != set(expected):
        raise ValueError("configuration fields must be complete and capability-local")
    by_key = {field.key: field for field in fields}
    return tuple(by_key[key] for key in SettingKey if key in by_key)

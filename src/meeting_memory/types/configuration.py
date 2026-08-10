"""Pure configuration, secret-reference, and provenance boundary data."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from meeting_memory.types.capabilities import Capability

SCHEMA_VERSION = 1
GENERATION_RE = re.compile(r"[0-9a-f]{32}")
REVISION_RE = re.compile(r"[0-9a-f]{64}")


class SettingKey(StrEnum):
    """Recognized compatibility names for runtime settings."""

    MEETINGS_DIR = "MEETINGS_DIR"
    MAX_RECORDING_MINUTES = "MAX_RECORDING_MINUTES"
    ASSEMBLYAI_API_KEY = "ASSEMBLYAI_API_KEY"
    B2_APPLICATION_KEY_ID = "B2_APPLICATION_KEY_ID"
    B2_APPLICATION_KEY = "B2_APPLICATION_KEY"
    B2_ENDPOINT = "B2_ENDPOINT"
    B2_REGION = "B2_REGION"
    B2_BUCKET_NAME = "B2_BUCKET_NAME"
    GOOGLE_CALENDAR_CREDENTIALS_FILE = "GOOGLE_CALENDAR_CREDENTIALS_FILE"
    GOOGLE_CALENDAR_ID = "GOOGLE_CALENDAR_ID"
    KNOWN_SPEAKERS = "KNOWN_SPEAKERS"
    NOTIFY_MINUTES_BEFORE = "NOTIFY_MINUTES_BEFORE"
    CALENDAR_POLL_INTERVAL = "CALENDAR_POLL_INTERVAL"
    ANTHROPIC_API_KEY = "ANTHROPIC_API_KEY"
    ANTHROPIC_MODEL = "ANTHROPIC_MODEL"
    SUMMARY_PROMPT_FILE = "SUMMARY_PROMPT_FILE"


class PreferenceKey(StrEnum):
    """The exhaustive allowlist that may be persisted outside Keychain."""

    MEETINGS_DIR = "MEETINGS_DIR"
    MAX_RECORDING_MINUTES = "MAX_RECORDING_MINUTES"
    B2_ENDPOINT = "B2_ENDPOINT"
    B2_REGION = "B2_REGION"
    B2_BUCKET_NAME = "B2_BUCKET_NAME"
    GOOGLE_CALENDAR_CREDENTIALS_FILE = "GOOGLE_CALENDAR_CREDENTIALS_FILE"
    GOOGLE_CALENDAR_ID = "GOOGLE_CALENDAR_ID"
    KNOWN_SPEAKERS = "KNOWN_SPEAKERS"
    NOTIFY_MINUTES_BEFORE = "NOTIFY_MINUTES_BEFORE"
    CALENDAR_POLL_INTERVAL = "CALENDAR_POLL_INTERVAL"
    ANTHROPIC_MODEL = "ANTHROPIC_MODEL"
    SUMMARY_PROMPT_FILE = "SUMMARY_PROMPT_FILE"

    @property
    def setting_key(self) -> SettingKey:
        return SettingKey(self.value)


class SecretId(StrEnum):
    """Atomic Keychain payload groups."""

    TRANSCRIPTION = "transcription"
    BACKUP = "backup"
    NOTES = "notes"


SECRET_KEYS = frozenset(
    {
        SettingKey.ASSEMBLYAI_API_KEY,
        SettingKey.B2_APPLICATION_KEY_ID,
        SettingKey.B2_APPLICATION_KEY,
        SettingKey.ANTHROPIC_API_KEY,
    }
)
OPTIONAL_CAPABILITIES = frozenset(Capability) - {Capability.RECORDING_CORE}


def secret_setting_keys(secret_id: SecretId) -> tuple[SettingKey, ...]:
    return {
        SecretId.TRANSCRIPTION: (SettingKey.ASSEMBLYAI_API_KEY,),
        SecretId.BACKUP: (
            SettingKey.B2_APPLICATION_KEY_ID,
            SettingKey.B2_APPLICATION_KEY,
        ),
        SecretId.NOTES: (SettingKey.ANTHROPIC_API_KEY,),
    }[secret_id]


@dataclass(frozen=True, slots=True)
class PreferenceValue:
    """One allowlisted non-secret app-owned value."""

    key: PreferenceKey
    value: str = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.key, PreferenceKey):
            raise ValueError("preferences accept only allowlisted non-secret keys")
        if not isinstance(self.value, str) or not self.value.strip():
            raise ValueError("preference values must not be blank")


@dataclass(frozen=True, slots=True)
class CapabilityPreference:
    """Explicit opt-in, opt-out, or compatibility behavior for one capability."""

    capability: Capability
    enabled: bool | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.capability, Capability):
            raise ValueError("capability preferences require a typed capability")
        if self.enabled is not None and type(self.enabled) is not bool:
            raise ValueError("capability enabled must be bool or None")
        if self.capability not in OPTIONAL_CAPABILITIES:
            raise ValueError("Recording Core cannot be disabled")


@dataclass(frozen=True, slots=True)
class SecretRef:
    """Opaque pointer that atomically activates one immutable Keychain generation."""

    secret_id: SecretId
    generation: str

    def __post_init__(self) -> None:
        if not isinstance(self.secret_id, SecretId):
            raise ValueError("secret references require a typed provider")
        if not isinstance(self.generation, str) or GENERATION_RE.fullmatch(self.generation) is None:
            raise ValueError("secret generation must be 32 lowercase hexadecimal characters")

    @property
    def account(self) -> str:
        return f"{self.secret_id.value}:{self.generation}"


class SecretValue:
    """One runtime secret with redacted object representation."""

    __slots__ = ("_key", "_value")

    def __init__(self, key: SettingKey, value: str) -> None:
        if not isinstance(key, SettingKey) or key not in SECRET_KEYS:
            raise ValueError("secret bundles accept only secret setting keys")
        if not isinstance(value, str) or not value.strip():
            raise ValueError("secret values must not be blank")
        object.__setattr__(self, "_key", key)
        object.__setattr__(self, "_value", value)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("SecretValue is immutable")

    def __deepcopy__(self, _memo):
        return self

    @property
    def key(self) -> SettingKey:
        return self._key

    @property
    def value(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return f"SecretValue(key={self.key!r}, value=<redacted>)"

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, SecretValue) and self.key is other.key and self.value == other.value
        )

    def __hash__(self) -> int:
        return hash((self.key, self.value))


class SecretBundle:
    """Typed, atomic provider secret payload."""

    __slots__ = ("_secret_id", "_values")

    def __init__(self, secret_id: SecretId, values: tuple[SecretValue, ...]) -> None:
        if not isinstance(secret_id, SecretId):
            raise ValueError("secret bundles require a typed provider")
        if not isinstance(values, tuple) or not all(
            isinstance(item, SecretValue) for item in values
        ):
            raise ValueError("secret bundles require typed secret values")
        keys = tuple(value.key for value in values)
        if len(keys) != len(set(keys)):
            raise ValueError("secret bundle contains duplicate fields")
        if set(keys) != set(secret_setting_keys(secret_id)):
            raise ValueError("secret bundle fields do not match its provider")
        object.__setattr__(self, "_secret_id", secret_id)
        object.__setattr__(self, "_values", tuple(values))

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("SecretBundle is immutable")

    def __deepcopy__(self, _memo):
        return self

    @property
    def secret_id(self) -> SecretId:
        return self._secret_id

    @property
    def values(self) -> tuple[SecretValue, ...]:
        return self._values

    def value_for(self, key: SettingKey) -> str | None:
        return next((item.value for item in self.values if item.key is key), None)

    def __repr__(self) -> str:
        return f"SecretBundle(secret_id={self.secret_id!r}, values=<redacted>)"


@dataclass(frozen=True, slots=True)
class SecretMaterial:
    """Decoded Keychain material bound to the exact activated reference."""

    ref: SecretRef
    bundle: SecretBundle = field(repr=False)

    def __post_init__(self) -> None:
        if self.ref.secret_id is not self.bundle.secret_id:
            raise ValueError("secret material reference and bundle must match")


@dataclass(frozen=True, slots=True)
class AppPreferences:
    """Complete non-secret atomic activation document."""

    values: tuple[PreferenceValue, ...] = ()
    capabilities: tuple[CapabilityPreference, ...] = ()
    secret_refs: tuple[SecretRef, ...] = ()
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported preferences schema version")
        _require_unique((item.key for item in self.values), "preference fields")
        _require_unique(
            (item.capability for item in self.capabilities),
            "capability preferences",
        )
        _require_unique((item.secret_id for item in self.secret_refs), "secret references")
        preference_order = {key: index for index, key in enumerate(PreferenceKey)}
        capability_order = {key: index for index, key in enumerate(Capability)}
        secret_order = {key: index for index, key in enumerate(SecretId)}
        object.__setattr__(
            self,
            "values",
            tuple(sorted(self.values, key=lambda item: preference_order[item.key])),
        )
        object.__setattr__(
            self,
            "capabilities",
            tuple(
                sorted(
                    self.capabilities,
                    key=lambda item: capability_order[item.capability],
                )
            ),
        )
        object.__setattr__(
            self,
            "secret_refs",
            tuple(sorted(self.secret_refs, key=lambda item: secret_order[item.secret_id])),
        )

    def value_for(self, key: PreferenceKey) -> str | None:
        return next((item.value for item in self.values if item.key is key), None)

    def enabled_for(self, capability: Capability) -> bool | None:
        return next(
            (item.enabled for item in self.capabilities if item.capability is capability),
            None,
        )

    def secret_ref_for(self, secret_id: SecretId) -> SecretRef | None:
        return next(
            (item for item in self.secret_refs if item.secret_id is secret_id),
            None,
        )


@dataclass(frozen=True, slots=True)
class PreferenceSnapshot:
    """One loaded document and the revision required for compare-and-swap."""

    preferences: AppPreferences
    revision: str | None

    def __post_init__(self) -> None:
        if self.revision is not None and REVISION_RE.fullmatch(self.revision) is None:
            raise ValueError("preference revision must be lowercase SHA-256")


def _require_unique(items, label: str) -> None:
    if len(values := tuple(items)) != len(set(values)):
        raise ValueError(f"{label} must be unique")

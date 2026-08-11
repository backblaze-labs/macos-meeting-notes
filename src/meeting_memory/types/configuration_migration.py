"""Value-free boundaries for explicit legacy environment migration."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration import SECRET_KEYS, SettingKey

_PREVIEW_ID_RE = re.compile(r"[0-9a-f]{32}")
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


class MigrationFieldState(StrEnum):
    """Whether one recognized legacy field can participate in migration."""

    ABSENT = "absent"
    IMPORTABLE = "importable"
    INVALID = "invalid"
    PRESERVED = "preserved"


class MigrationPreviewState(StrEnum):
    """Terminal state of one explicit preview request."""

    READY = "ready"
    EMPTY = "empty"
    FAILED = "failed"


class MigrationOutcomeState(StrEnum):
    """Safe terminal states for a confirmed apply attempt."""

    APPLIED = "applied"
    STALE_SOURCE = "stale_source"
    PREFERENCES_CONFLICT = "preferences_conflict"
    KEYCHAIN_FAILED = "keychain_failed"
    DURABILITY_UNCERTAIN = "durability_uncertain"
    ACTIVATION_UNCERTAIN = "activation_uncertain"
    CLEANUP_FAILED = "cleanup_failed"
    REJECTED = "rejected"
    FAILED = "failed"


class MigrationPreviewId:
    """Opaque, single-use identifier with no source fingerprint content."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        if not isinstance(value, str) or _PREVIEW_ID_RE.fullmatch(value) is None:
            raise ValueError("migration preview identifier is invalid")
        object.__setattr__(self, "_value", value)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("migration preview identifier is immutable")

    @property
    def value(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "MigrationPreviewId(<opaque>)"

    __str__ = __repr__

    def __eq__(self, other: object) -> bool:
        return isinstance(other, MigrationPreviewId) and self.value == other.value

    def __hash__(self) -> int:
        return hash(self.value)

    def __deepcopy__(self, _memo):
        return self


@dataclass(frozen=True, slots=True)
class MigrationField:
    """Value-free preview metadata for one exact setting name."""

    capability: Capability
    key: SettingKey
    state: MigrationFieldState
    secret: bool
    process_present: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.capability, Capability) or not isinstance(self.key, SettingKey):
            raise ValueError("migration fields require typed capability and setting keys")
        if not isinstance(self.state, MigrationFieldState):
            raise ValueError("migration fields require a typed state")
        if type(self.secret) is not bool or type(self.process_present) is not bool:
            raise ValueError("migration field flags must be boolean")
        if _SETTING_CAPABILITY[self.key] is not self.capability:
            raise ValueError("migration field does not belong to its capability")
        if self.secret != (self.key in SECRET_KEYS):
            raise ValueError("migration field secret classification is invalid")


@dataclass(frozen=True, slots=True)
class MigrationCandidate:
    """One atomic capability selection offered by a preview."""

    capability: Capability
    fields: tuple[MigrationField, ...]
    selectable: bool

    def __post_init__(self) -> None:
        if not isinstance(self.capability, Capability) or type(self.selectable) is not bool:
            raise ValueError("migration candidates require typed boundary values")
        by_key = {field.key: field for field in self.fields}
        if len(by_key) != len(self.fields) or any(
            field.capability is not self.capability for field in self.fields
        ):
            raise ValueError("migration candidate fields must be unique and capability-local")
        if self.selectable and (
            not any(field.state is MigrationFieldState.IMPORTABLE for field in self.fields)
            or any(field.state is MigrationFieldState.INVALID for field in self.fields)
        ):
            raise ValueError("selectable migration candidate must be importable and valid")
        object.__setattr__(
            self,
            "fields",
            tuple(by_key[key] for key in SettingKey if key in by_key),
        )


@dataclass(frozen=True, slots=True)
class MigrationPreview:
    """Public, serializable-safe description of a private bound plan."""

    preview_id: MigrationPreviewId
    state: MigrationPreviewState
    candidates: tuple[MigrationCandidate, ...]
    summary: str
    action: str

    def __post_init__(self) -> None:
        if not isinstance(self.state, MigrationPreviewState):
            raise ValueError("migration preview requires a typed state")
        by_capability = {item.capability: item for item in self.candidates}
        if len(by_capability) != len(self.candidates) or set(by_capability) != set(Capability):
            raise ValueError("migration preview requires every capability exactly once")
        if not self.summary.strip() or not self.action.strip():
            raise ValueError("migration preview requires safe summary and action text")
        selectable = any(item.selectable for item in self.candidates)
        if (self.state is MigrationPreviewState.READY) != selectable:
            raise ValueError("migration preview state does not match its candidates")
        object.__setattr__(
            self,
            "candidates",
            tuple(by_capability[capability] for capability in Capability),
        )


@dataclass(frozen=True, slots=True)
class MigrationConfirmation:
    """Explicit selection bound to one opaque preview."""

    preview_id: MigrationPreviewId
    selected: tuple[Capability, ...]
    confirmed: bool

    def __post_init__(self) -> None:
        if not isinstance(self.preview_id, MigrationPreviewId) or self.confirmed is not True:
            raise ValueError("migration confirmation requires typed boundary values")
        selected = set(self.selected)
        if (
            not self.selected
            or len(selected) != len(self.selected)
            or not all(isinstance(item, Capability) for item in self.selected)
        ):
            raise ValueError("migration selection must be non-empty, typed, and unique")
        object.__setattr__(
            self,
            "selected",
            tuple(capability for capability in Capability if capability in selected),
        )


@dataclass(frozen=True, slots=True)
class MigrationOutcome:
    """Value-free terminal result suitable for a future worker event."""

    state: MigrationOutcomeState
    selected: tuple[Capability, ...]
    summary: str
    action: str

    def __post_init__(self) -> None:
        if not isinstance(self.state, MigrationOutcomeState):
            raise ValueError("migration outcome requires a typed state")
        selected = set(self.selected)
        if len(selected) != len(self.selected) or not all(
            isinstance(item, Capability) for item in self.selected
        ):
            raise ValueError("migration outcome capabilities must be typed and unique")
        if not self.summary.strip() or not self.action.strip():
            raise ValueError("migration outcome requires safe summary and action text")
        object.__setattr__(
            self,
            "selected",
            tuple(capability for capability in Capability if capability in selected),
        )

    @property
    def activated(self) -> bool:
        """Whether the intended replacement is confirmed visible to readers."""

        return self.state in {
            MigrationOutcomeState.APPLIED,
            MigrationOutcomeState.DURABILITY_UNCERTAIN,
        }

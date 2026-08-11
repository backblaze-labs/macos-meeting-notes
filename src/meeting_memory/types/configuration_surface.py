"""Typed, redacted worker events for the native configuration surface."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from meeting_memory.types.calendar_authorization import CalendarAuthorizationOutcome
from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration_editing import (
    CapabilityConfiguration,
    ConfigurationOperationId,
    ConfigurationSaveOutcome,
)
from meeting_memory.types.configuration_migration import MigrationOutcome, MigrationPreview


class SurfaceOperationKind(StrEnum):
    CONFIGURATION = "configuration"
    MIGRATION = "migration"
    CALENDAR_AUTHORIZATION = "calendar_authorization"
    NOTES_PROMPT = "notes_prompt"


class PromptOperationState(StrEnum):
    LOADED = "loaded"
    SAVED = "saved"
    FAILED = "failed"


class PromptDraft:
    """Private prompt text with a redacted public object surface."""

    __slots__ = ("_text",)

    def __init__(self, text: str) -> None:
        if not isinstance(text, str):
            raise ValueError("prompt draft must be text")
        object.__setattr__(self, "_text", text)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("prompt drafts are immutable")

    @property
    def text(self) -> str:
        return self._text

    def __repr__(self) -> str:
        return "PromptDraft(<redacted>)"

    __str__ = __repr__

    def __deepcopy__(self, _memo):
        return self


class PromptDestination:
    """UI-readable destination whose diagnostics remain value-free."""

    __slots__ = ("_value",)

    def __init__(self, value: Path) -> None:
        if (
            not isinstance(value, Path)
            or not str(value).strip()
            or any(character in str(value) for character in ("\x00", "\n", "\r"))
        ):
            raise ValueError("prompt destination must be a safe path")
        object.__setattr__(self, "_value", value)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("prompt destinations are immutable")

    @property
    def value(self) -> str:
        return str(self._value)

    def __repr__(self) -> str:
        return "PromptDestination(<redacted>)"

    __str__ = __repr__

    def __deepcopy__(self, _memo):
        return self


@dataclass(frozen=True, slots=True)
class PromptOutcome:
    state: PromptOperationState
    summary: str
    action: str
    destination: PromptDestination | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, PromptOperationState):
            raise ValueError("prompt outcome state must be typed")
        _safe_copy(self.summary, self.action)
        if self.destination is not None and not isinstance(self.destination, PromptDestination):
            raise ValueError("prompt destination must be typed")
        if (self.state is PromptOperationState.SAVED) != (self.destination is not None):
            raise ValueError("saved prompt outcome requires its destination")


@dataclass(frozen=True, slots=True)
class ConfigurationOpened:
    operation_id: ConfigurationOperationId
    configuration: CapabilityConfiguration

    def __post_init__(self) -> None:
        _event(self.operation_id, self.configuration, CapabilityConfiguration)


@dataclass(frozen=True, slots=True)
class ConfigurationOpenFailed:
    operation_id: ConfigurationOperationId
    capability: Capability
    summary: str = "Configuration could not be loaded safely."
    action: str = "Close the form and try again."

    def __post_init__(self) -> None:
        _operation(self.operation_id)
        if not isinstance(self.capability, Capability):
            raise ValueError("configuration failure requires a typed capability")
        _safe_copy(self.summary, self.action)


@dataclass(frozen=True, slots=True)
class ConfigurationSaved:
    operation_id: ConfigurationOperationId
    outcome: ConfigurationSaveOutcome
    runtime_pause_succeeded: bool

    def __post_init__(self) -> None:
        _event(self.operation_id, self.outcome, ConfigurationSaveOutcome)
        if type(self.runtime_pause_succeeded) is not bool:
            raise ValueError("runtime pause result must be boolean")


@dataclass(frozen=True, slots=True)
class MigrationPreviewed:
    operation_id: ConfigurationOperationId
    preview: MigrationPreview

    def __post_init__(self) -> None:
        _event(self.operation_id, self.preview, MigrationPreview)


@dataclass(frozen=True, slots=True)
class MigrationPreviewFailed:
    operation_id: ConfigurationOperationId
    summary: str = "Legacy configuration could not be previewed safely."
    action: str = "Check the legacy source and try again."

    def __post_init__(self) -> None:
        _operation(self.operation_id)
        _safe_copy(self.summary, self.action)


@dataclass(frozen=True, slots=True)
class MigrationApplied:
    operation_id: ConfigurationOperationId
    outcome: MigrationOutcome
    runtime_pause_succeeded: bool

    def __post_init__(self) -> None:
        _event(self.operation_id, self.outcome, MigrationOutcome)
        if type(self.runtime_pause_succeeded) is not bool:
            raise ValueError("runtime pause result must be boolean")


@dataclass(frozen=True, slots=True)
class CalendarAuthorizationFinished:
    operation_id: ConfigurationOperationId
    outcome: CalendarAuthorizationOutcome

    def __post_init__(self) -> None:
        _event(self.operation_id, self.outcome, CalendarAuthorizationOutcome)


@dataclass(frozen=True, slots=True)
class PromptLoaded:
    operation_id: ConfigurationOperationId
    outcome: PromptOutcome

    def __post_init__(self) -> None:
        _event(self.operation_id, self.outcome, PromptOutcome)
        if self.outcome.state not in {PromptOperationState.LOADED, PromptOperationState.FAILED}:
            raise ValueError("prompt load event has an invalid terminal state")


@dataclass(frozen=True, slots=True)
class PromptSaved:
    operation_id: ConfigurationOperationId
    outcome: PromptOutcome

    def __post_init__(self) -> None:
        _event(self.operation_id, self.outcome, PromptOutcome)
        if self.outcome.state not in {PromptOperationState.SAVED, PromptOperationState.FAILED}:
            raise ValueError("prompt save event has an invalid terminal state")


def _operation(operation: object) -> None:
    if not isinstance(operation, ConfigurationOperationId):
        raise ValueError("surface events require a typed operation identifier")


def _event(operation: object, payload: object, expected: type) -> None:
    _operation(operation)
    if not isinstance(payload, expected):
        raise ValueError("surface event payload has the wrong type")


def _safe_copy(*values: object) -> None:
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError("surface event copy must be nonblank text")

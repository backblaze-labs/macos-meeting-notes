"""Shared worker and service fakes for configuration-surface tests."""

from meeting_memory.config.schema import definitions_for
from meeting_memory.types.calendar_authorization import (
    CalendarAuthorizationOutcome,
    CalendarAuthorizationState,
)
from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration_editing import (
    CapabilityConfiguration,
    ConfigurationChange,
    ConfigurationEditId,
    ConfigurationField,
    ConfigurationSaveOutcome,
    ConfigurationSaveState,
    ConfigurationValue,
    SecretAvailability,
)
from meeting_memory.types.configuration_migration import (
    MigrationOutcome,
    MigrationOutcomeState,
)


class ImmediateThread:
    def __init__(self, *, target, args=(), daemon=False):
        self.target = target
        self.args = args
        self.daemon = daemon

    def start(self) -> None:
        self.target(*self.args)


class DeferredThread(ImmediateThread):
    instances = []

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.__class__.instances.append(self)

    def start(self) -> None:
        return None


class FailingThread(ImmediateThread):
    def start(self) -> None:
        raise RuntimeError("thread-sentinel")


class SecondFailThread(ImmediateThread):
    starts = 0

    def start(self) -> None:
        self.__class__.starts += 1
        if self.__class__.starts > 1:
            raise RuntimeError("thread-sentinel")
        super().start()


class IdFactory:
    def __init__(self) -> None:
        self.index = 0

    def __call__(self) -> str:
        self.index += 1
        return f"{self.index:032x}"


class Configuration:
    def __init__(self, save_outcome=None, order=None, open_result=None) -> None:
        self.save_outcome = save_outcome
        self.order = order
        self.open_result = open_result

    def open(self, _capability):
        if self.open_result is None:
            raise RuntimeError("not used")
        return self.open_result

    def save(self, change):
        if self.order is not None:
            self.order.append("save")
        return self.save_outcome or ConfigurationSaveOutcome(
            ConfigurationSaveState.UNCHANGED,
            change.capability,
            "Unchanged.",
            "Nothing needed.",
        )


class Migration:
    def __init__(self, outcome=None, preview=None) -> None:
        self.outcome = outcome
        self.preview_result = preview

    def preview(self, **_kwargs):
        if self.preview_result is None:
            raise RuntimeError("preview-sentinel")
        return self.preview_result

    def apply(self, confirmation):
        return self.outcome or MigrationOutcome(
            MigrationOutcomeState.REJECTED,
            confirmation.selected,
            "Rejected.",
            "Retry.",
        )


class Authorization:
    def authorize(self):
        return CalendarAuthorizationOutcome(
            CalendarAuthorizationState.AUTHORIZED,
            "Authorized.",
            "Restart.",
        )


class Pause:
    def __init__(self, order, fail=None) -> None:
        self.order = order
        self.fail = fail

    def pause(self, capability) -> bool:
        self.order.append(f"pause:{capability.value}")
        return capability is not self.fail


def disable_change(capability: Capability) -> ConfigurationChange:
    fields = tuple(
        ConfigurationField(definition.key, ConfigurationValue("configured"))
        for definition in definitions_for(capability)
        if not definition.secret
    )
    return ConfigurationChange(
        ConfigurationEditId("c" * 32),
        capability,
        False,
        fields,
    )


def configuration_view(capability: Capability) -> CapabilityConfiguration:
    change = disable_change(capability)
    return CapabilityConfiguration(
        change.edit_id,
        capability,
        False,
        change.fields,
        SecretAvailability.UNAVAILABLE,
        False,
        False,
        False,
    )

"""Hostile construction and redaction tests for configuration UI boundaries."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict

import pytest

from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration import (
    SecretBundle,
    SecretId,
    SecretValue,
    SettingKey,
)
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

EDIT_ID = ConfigurationEditId("a" * 32)


def test_configuration_view_requires_complete_nonsecret_capability_fields() -> None:
    with pytest.raises(ValueError):
        _view(
            Capability.BACKUP,
            (_field(SettingKey.ASSEMBLYAI_API_KEY),),
        )


def test_configuration_fields_are_canonicalized_for_stable_native_forms() -> None:
    fields = tuple(reversed(_fields(Capability.CALENDAR)))

    view = _view(Capability.CALENDAR, fields)
    change = ConfigurationChange(
        EDIT_ID,
        Capability.CALENDAR,
        False,
        fields,
    )

    expected = [key for key in SettingKey if key in {field.key for field in fields}]
    assert [field.key for field in view.fields] == expected
    assert [field.key for field in change.fields] == expected
    with pytest.raises(ValueError):
        _view(
            Capability.BACKUP,
            (_field(SettingKey.B2_ENDPOINT),),
        )
    with pytest.raises(ValueError):
        _view(
            Capability.BACKUP,
            (*_fields(Capability.BACKUP), _field(SettingKey.B2_ENDPOINT)),
        )


def test_configuration_change_rejects_mismatched_or_forbidden_secret_bundle() -> None:
    notes_secret = SecretBundle(
        SecretId.NOTES,
        (SecretValue(SettingKey.ANTHROPIC_API_KEY, "secret-sentinel"),),
    )

    with pytest.raises(ValueError):
        ConfigurationChange(
            EDIT_ID,
            Capability.BACKUP,
            True,
            _fields(Capability.BACKUP),
            notes_secret,
            disclosure_confirmed=True,
        )
    with pytest.raises(ValueError):
        ConfigurationChange(
            EDIT_ID,
            Capability.RECORDING_CORE,
            None,
            _fields(Capability.RECORDING_CORE),
            notes_secret,
        )


def test_optional_enable_requires_disclosure_confirmation() -> None:
    with pytest.raises(ValueError):
        ConfigurationChange(
            EDIT_ID,
            Capability.TRANSCRIPTION,
            True,
            _fields(Capability.TRANSCRIPTION),
        )

    change = ConfigurationChange(
        EDIT_ID,
        Capability.TRANSCRIPTION,
        True,
        _fields(Capability.TRANSCRIPTION),
        disclosure_confirmed=True,
    )
    assert change.enabled is True


def test_recording_core_cannot_express_optional_enablement() -> None:
    with pytest.raises(ValueError):
        _view(Capability.RECORDING_CORE, preference=False)
    with pytest.raises(ValueError):
        ConfigurationChange(
            EDIT_ID,
            Capability.RECORDING_CORE,
            False,
            _fields(Capability.RECORDING_CORE),
        )


def test_secret_availability_is_capability_local() -> None:
    with pytest.raises(ValueError):
        CapabilityConfiguration(
            EDIT_ID,
            Capability.CALENDAR,
            None,
            _fields(Capability.CALENDAR),
            SecretAvailability.AVAILABLE,
            False,
            False,
            False,
        )
    with pytest.raises(ValueError):
        CapabilityConfiguration(
            EDIT_ID,
            Capability.NOTES,
            None,
            _fields(Capability.NOTES),
            SecretAvailability.NONE,
            False,
            False,
            False,
        )


def test_secret_and_nonsecret_values_are_redacted_from_object_graphs() -> None:
    sentinel = "secret-sentinel"
    change = ConfigurationChange(
        EDIT_ID,
        Capability.NOTES,
        True,
        _fields(Capability.NOTES, sentinel),
        SecretBundle(
            SecretId.NOTES,
            (SecretValue(SettingKey.ANTHROPIC_API_KEY, sentinel),),
        ),
        disclosure_confirmed=True,
    )
    view = _view(Capability.NOTES, fields=_fields(Capability.NOTES, sentinel))

    assert sentinel not in repr(change)
    assert deepcopy(change) is change
    assert sentinel not in repr(view)
    assert sentinel not in repr(asdict(view))


@pytest.mark.parametrize(
    "state",
    [
        ConfigurationSaveState.UNCHANGED,
        ConfigurationSaveState.REJECTED,
        ConfigurationSaveState.PREFERENCES_CONFLICT,
        ConfigurationSaveState.KEYCHAIN_FAILED,
        ConfigurationSaveState.FAILED,
    ],
)
def test_nonactivated_outcomes_cannot_request_restart_or_pause(
    state: ConfigurationSaveState,
) -> None:
    with pytest.raises(ValueError):
        ConfigurationSaveOutcome(
            state,
            Capability.BACKUP,
            "Safe summary.",
            "Safe action.",
            restart_required=True,
        )
    with pytest.raises(ValueError):
        ConfigurationSaveOutcome(
            state,
            Capability.BACKUP,
            "Safe summary.",
            "Safe action.",
            pause_current_session=True,
        )


def test_session_paused_outcome_only_allows_runtime_pause() -> None:
    outcome = ConfigurationSaveOutcome(
        ConfigurationSaveState.SESSION_PAUSED,
        Capability.BACKUP,
        "Safe summary.",
        "Safe action.",
        pause_current_session=True,
        process_reenables=True,
    )

    assert outcome.restart_required is False
    with pytest.raises(ValueError):
        ConfigurationSaveOutcome(
            ConfigurationSaveState.SESSION_PAUSED,
            Capability.BACKUP,
            "Safe summary.",
            "Safe action.",
        )
    with pytest.raises(ValueError):
        ConfigurationSaveOutcome(
            ConfigurationSaveState.SESSION_PAUSED,
            Capability.BACKUP,
            "Safe summary.",
            "Safe action.",
            restart_required=True,
            pause_current_session=True,
        )


def _view(
    capability: Capability,
    fields: tuple[ConfigurationField, ...] | None = None,
    *,
    preference: bool | None = None,
) -> CapabilityConfiguration:
    return CapabilityConfiguration(
        EDIT_ID,
        capability,
        preference,
        fields if fields is not None else _fields(capability),
        (
            SecretAvailability.NONE
            if capability in {Capability.RECORDING_CORE, Capability.CALENDAR}
            else SecretAvailability.UNAVAILABLE
        ),
        False,
        False,
        False,
    )


def _fields(
    capability: Capability,
    value: str = "configured-value",
) -> tuple[ConfigurationField, ...]:
    secret_keys = {
        SettingKey.ASSEMBLYAI_API_KEY,
        SettingKey.B2_APPLICATION_KEY_ID,
        SettingKey.B2_APPLICATION_KEY,
        SettingKey.ANTHROPIC_API_KEY,
    }
    capability_keys = {
        Capability.RECORDING_CORE: (
            SettingKey.MEETINGS_DIR,
            SettingKey.MAX_RECORDING_MINUTES,
        ),
        Capability.TRANSCRIPTION: (SettingKey.ASSEMBLYAI_API_KEY,),
        Capability.BACKUP: (
            SettingKey.B2_APPLICATION_KEY_ID,
            SettingKey.B2_APPLICATION_KEY,
            SettingKey.B2_ENDPOINT,
            SettingKey.B2_REGION,
            SettingKey.B2_BUCKET_NAME,
        ),
        Capability.CALENDAR: (
            SettingKey.GOOGLE_CALENDAR_CREDENTIALS_FILE,
            SettingKey.GOOGLE_CALENDAR_ID,
            SettingKey.KNOWN_SPEAKERS,
            SettingKey.NOTIFY_MINUTES_BEFORE,
            SettingKey.CALENDAR_POLL_INTERVAL,
        ),
        Capability.NOTES: (
            SettingKey.ANTHROPIC_API_KEY,
            SettingKey.ANTHROPIC_MODEL,
            SettingKey.SUMMARY_PROMPT_FILE,
        ),
    }
    return tuple(
        _field(key, value) for key in capability_keys[capability] if key not in secret_keys
    )


def _field(key: SettingKey, value: str = "configured-value") -> ConfigurationField:
    return ConfigurationField(key, ConfigurationValue(value))

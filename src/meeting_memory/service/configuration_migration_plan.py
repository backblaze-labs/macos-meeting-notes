"""Pure tri-state planning for explicit legacy environment migration."""

from __future__ import annotations

from collections.abc import Mapping

from meeting_memory.config.schema import definitions_for, required_keys, secret_id_for
from meeting_memory.config.settings import Settings
from meeting_memory.config.validation import configured_value, valid_required_setting
from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration import (
    AppPreferences,
    CapabilityPreference,
    PreferenceKey,
    PreferenceValue,
    SecretBundle,
    SecretId,
    SecretRef,
    SecretValue,
    SettingKey,
    secret_setting_keys,
)
from meeting_memory.types.configuration_migration import (
    MigrationCandidate,
    MigrationField,
    MigrationFieldState,
)


class MigrationPlan:
    """Ephemeral plan whose raw parsed values never enter its representation."""

    __slots__ = ("_candidates", "_preferences", "_values")

    def __init__(
        self,
        candidates: tuple[MigrationCandidate, ...],
        preferences: AppPreferences,
        values: Mapping[SettingKey, str],
    ) -> None:
        self._candidates = candidates
        self._preferences = preferences
        self._values = dict(values)

    @property
    def candidates(self) -> tuple[MigrationCandidate, ...]:
        return self._candidates

    @property
    def selectable(self) -> tuple[Capability, ...]:
        return tuple(item.capability for item in self.candidates if item.selectable)

    def secret_bundles(self, selected: tuple[Capability, ...]) -> tuple[SecretBundle, ...]:
        bundles: list[SecretBundle] = []
        for secret_id in SecretId:
            capability = _secret_capability(secret_id)
            if capability not in selected or self._preferences.secret_ref_for(secret_id):
                continue
            bundles.append(
                SecretBundle(
                    secret_id,
                    tuple(
                        SecretValue(key, self._values[key])
                        for key in secret_setting_keys(secret_id)
                    ),
                )
            )
        return tuple(bundles)

    def replacement(
        self,
        selected: tuple[Capability, ...],
        new_refs: tuple[SecretRef, ...],
    ) -> AppPreferences:
        values = list(self._preferences.values)
        capabilities = {item.capability: item for item in self._preferences.capabilities}
        refs = [*self._preferences.secret_refs, *new_refs]
        existing_keys = {item.key for item in values}
        for capability in selected:
            for definition in definitions_for(capability):
                if definition.secret or definition.key not in self._values:
                    continue
                key = PreferenceKey(definition.key.value)
                if key not in existing_keys:
                    values.append(PreferenceValue(key, self._values[definition.key]))
                    existing_keys.add(key)
            if (
                capability is not Capability.RECORDING_CORE
                and self._preferences.enabled_for(capability) is None
            ):
                capabilities[capability] = CapabilityPreference(capability, True)
        return AppPreferences(tuple(values), tuple(capabilities.values()), tuple(refs))

    def __repr__(self) -> str:
        return "MigrationPlan(candidates=<safe>, preferences=<redacted>, values=<redacted>)"


def build_migration_plan(
    values: Mapping[SettingKey, str],
    preferences: AppPreferences,
    process_keys: frozenset[SettingKey] = frozenset(),
) -> MigrationPlan:
    """Build canonical candidates without using process values as import material."""

    candidates = tuple(
        _candidate(capability, values, preferences, process_keys) for capability in Capability
    )
    return MigrationPlan(candidates, preferences, values)


def _candidate(
    capability: Capability,
    values: Mapping[SettingKey, str],
    preferences: AppPreferences,
    process_keys: frozenset[SettingKey],
) -> MigrationCandidate:
    fields = tuple(
        _field(capability, definition.key, definition.secret, values, preferences, process_keys)
        for definition in definitions_for(capability)
    )
    selectable = _selectable(capability, fields, values, preferences)
    return MigrationCandidate(capability, fields, selectable)


def _field(
    capability: Capability,
    key: SettingKey,
    secret: bool,
    values: Mapping[SettingKey, str],
    preferences: AppPreferences,
    process_keys: frozenset[SettingKey],
) -> MigrationField:
    managed_value = None if secret else preferences.value_for(PreferenceKey(key.value))
    managed = (
        preferences.secret_ref_for(secret_id_for(key)) is not None
        if secret
        else managed_value is not None
    )
    if managed:
        state = (
            MigrationFieldState.INVALID
            if not secret and not _valid_value(key, managed_value)
            else MigrationFieldState.PRESERVED
        )
    elif key not in values:
        state = MigrationFieldState.ABSENT
    elif _valid_value(key, values[key]):
        state = MigrationFieldState.IMPORTABLE
    else:
        state = MigrationFieldState.INVALID
    return MigrationField(capability, key, state, secret, key in process_keys)


def _selectable(
    capability: Capability,
    fields: tuple[MigrationField, ...],
    values: Mapping[SettingKey, str],
    preferences: AppPreferences,
) -> bool:
    if not any(field.state is MigrationFieldState.IMPORTABLE for field in fields):
        return False
    if any(field.state is MigrationFieldState.INVALID for field in fields):
        return False
    if capability is Capability.RECORDING_CORE:
        return all(_managed_value_valid(field.key, preferences) for field in fields)
    preference = preferences.enabled_for(capability)
    if preference is False:
        return False
    secret_id = _capability_secret(capability)
    if preference is None and secret_id and preferences.secret_ref_for(secret_id):
        return False
    for key in required_keys(capability):
        value = _selected_value(key, values, preferences)
        if value is None or not valid_required_setting(key, value):
            return False
    return all(_managed_value_valid(field.key, preferences) for field in fields)


def _managed_value_valid(key: SettingKey, preferences: AppPreferences) -> bool:
    try:
        value = preferences.value_for(PreferenceKey(key.value))
    except ValueError:
        return True
    return value is None or _valid_value(key, value)


def _selected_value(
    key: SettingKey,
    values: Mapping[SettingKey, str],
    preferences: AppPreferences,
) -> object:
    secret_id = secret_id_for(key)
    if secret_id is not None:
        return True if preferences.secret_ref_for(secret_id) is not None else values.get(key)
    return preferences.value_for(PreferenceKey(key.value)) or values.get(key)


def _valid_value(key: SettingKey, value: object) -> bool:
    if not configured_value(value):
        return False
    if key in {
        SettingKey.MEETINGS_DIR,
        SettingKey.GOOGLE_CALENDAR_CREDENTIALS_FILE,
        SettingKey.SUMMARY_PROMPT_FILE,
    } and "\x00" in str(value):
        return False
    if key in required_keys(_key_capability(key)):
        return valid_required_setting(key, value)
    try:
        if key is SettingKey.MAX_RECORDING_MINUTES:
            return int(str(value)) > 0
        if key is SettingKey.NOTIFY_MINUTES_BEFORE:
            return int(str(value)) >= 0
        if key is SettingKey.CALENDAR_POLL_INTERVAL:
            return int(str(value)) > 0
        if key is SettingKey.KNOWN_SPEAKERS:
            Settings.parse_known_speakers(value)
    except (TypeError, ValueError):
        return False
    return True


def _key_capability(key: SettingKey) -> Capability:
    return next(
        capability
        for capability in Capability
        if key in {item.key for item in definitions_for(capability)}
    )


def _capability_secret(capability: Capability) -> SecretId | None:
    return next(
        (
            secret_id_for(item.key)
            for item in definitions_for(capability)
            if secret_id_for(item.key) is not None
        ),
        None,
    )


def _secret_capability(secret_id: SecretId) -> Capability:
    return _key_capability(secret_setting_keys(secret_id)[0])

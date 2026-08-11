"""Pure tri-state planning tests for Stage 4C migration."""

from __future__ import annotations

import pytest

from meeting_memory.service.configuration_migration_plan import build_migration_plan
from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration import (
    AppPreferences,
    CapabilityPreference,
    PreferenceKey,
    PreferenceValue,
    SecretId,
    SecretRef,
    SettingKey,
)
from meeting_memory.types.configuration_migration import MigrationFieldState


def test_complete_legacy_groups_are_canonical_and_selected_bundles_are_atomic() -> None:
    values = {
        SettingKey.ASSEMBLYAI_API_KEY: "assembly-secret",
        SettingKey.B2_APPLICATION_KEY_ID: "b2-id",
        SettingKey.B2_APPLICATION_KEY: "b2-secret",
        SettingKey.B2_ENDPOINT: "https://s3.example.invalid",
        SettingKey.B2_REGION: "region",
        SettingKey.B2_BUCKET_NAME: "bucket",
        SettingKey.ANTHROPIC_API_KEY: "notes-secret",
    }

    plan = build_migration_plan(values, AppPreferences())
    bundles = plan.secret_bundles((Capability.BACKUP, Capability.NOTES))

    assert plan.selectable == (
        Capability.TRANSCRIPTION,
        Capability.BACKUP,
        Capability.NOTES,
    )
    assert tuple(bundle.secret_id for bundle in bundles) == (SecretId.BACKUP, SecretId.NOTES)
    assert len(bundles[0].values) == 2
    assert "assembly-secret" not in repr(plan)
    assert "b2-secret" not in repr(plan)


@pytest.mark.parametrize(
    ("key", "value", "capability"),
    [
        (SettingKey.SUMMARY_PROMPT_FILE, "", Capability.NOTES),
        (SettingKey.ANTHROPIC_MODEL, "replace-me", Capability.NOTES),
        (SettingKey.KNOWN_SPEAKERS, "{broken", Capability.CALENDAR),
        (SettingKey.NOTIFY_MINUTES_BEFORE, "-1", Capability.CALENDAR),
        (SettingKey.MAX_RECORDING_MINUTES, "0", Capability.RECORDING_CORE),
        (SettingKey.MEETINGS_DIR, "bad\x00path", Capability.RECORDING_CORE),
        (SettingKey.B2_ENDPOINT, "http://example.invalid", Capability.BACKUP),
    ],
)
def test_any_recognized_invalid_missing_app_value_blocks_capability(
    key: SettingKey,
    value: str,
    capability: Capability,
) -> None:
    values = _minimum_group(capability)
    values[key] = value

    plan = build_migration_plan(values, AppPreferences())
    candidate = _candidate(plan, capability)

    assert candidate.selectable is False
    assert (
        next(field for field in candidate.fields if field.key is key).state
        is MigrationFieldState.INVALID
    )


def test_explicit_false_blocks_true_repairs_and_inactive_ref_blocks_activation() -> None:
    legacy = _minimum_group(Capability.BACKUP)
    disabled = AppPreferences(
        capabilities=(CapabilityPreference(Capability.BACKUP, False),),
    )
    enabled = AppPreferences(
        capabilities=(CapabilityPreference(Capability.BACKUP, True),),
        values=(PreferenceValue(PreferenceKey.B2_REGION, "app-region"),),
    )
    inactive_ref = AppPreferences(
        secret_refs=(SecretRef(SecretId.BACKUP, "a" * 32),),
    )

    assert _candidate(build_migration_plan(legacy, disabled), Capability.BACKUP).selectable is False
    repaired = build_migration_plan(legacy, enabled)
    assert _candidate(repaired, Capability.BACKUP).selectable is True
    replacement = repaired.replacement(
        (Capability.BACKUP,),
        (SecretRef(SecretId.BACKUP, "b" * 32),),
    )
    assert replacement.enabled_for(Capability.BACKUP) is True
    assert replacement.value_for(PreferenceKey.B2_REGION) == "app-region"
    assert (
        _candidate(build_migration_plan(legacy, inactive_ref), Capability.BACKUP).selectable
        is False
    )


def test_invalid_managed_value_is_reported_invalid_without_being_overwritten() -> None:
    legacy = _minimum_group(Capability.BACKUP)
    preferences = AppPreferences(
        values=(PreferenceValue(PreferenceKey.B2_ENDPOINT, "http://app.invalid"),),
        capabilities=(CapabilityPreference(Capability.BACKUP, True),),
    )

    plan = build_migration_plan(legacy, preferences)
    candidate = _candidate(plan, Capability.BACKUP)

    assert candidate.selectable is False
    assert (
        next(field.state for field in candidate.fields if field.key is SettingKey.B2_ENDPOINT)
        is MigrationFieldState.INVALID
    )


def test_merge_fills_only_missing_preserves_unselected_and_never_adds_core_flag() -> None:
    preferences = AppPreferences(
        values=(
            PreferenceValue(PreferenceKey.MEETINGS_DIR, "/app/meetings"),
            PreferenceValue(PreferenceKey.GOOGLE_CALENDAR_ID, "app-calendar"),
        ),
        capabilities=(CapabilityPreference(Capability.CALENDAR, None),),
    )
    values = {
        SettingKey.MEETINGS_DIR: "/legacy/meetings",
        SettingKey.MAX_RECORDING_MINUTES: "90",
        SettingKey.GOOGLE_CALENDAR_CREDENTIALS_FILE: "relative/credentials.json",
        SettingKey.GOOGLE_CALENDAR_ID: "legacy-calendar",
    }
    plan = build_migration_plan(values, preferences)

    replacement = plan.replacement((Capability.RECORDING_CORE, Capability.CALENDAR), ())

    assert replacement.value_for(PreferenceKey.MEETINGS_DIR) == "/app/meetings"
    assert replacement.value_for(PreferenceKey.MAX_RECORDING_MINUTES) == "90"
    assert replacement.value_for(PreferenceKey.GOOGLE_CALENDAR_ID) == "app-calendar"
    assert replacement.value_for(PreferenceKey.GOOGLE_CALENDAR_CREDENTIALS_FILE) == (
        "relative/credentials.json"
    )
    assert replacement.enabled_for(Capability.CALENDAR) is True
    assert all(
        item.capability is not Capability.RECORDING_CORE for item in replacement.capabilities
    )


def test_process_presence_is_diagnostic_only_and_strings_are_not_normalized() -> None:
    raw = "./relative/../meetings"
    plan = build_migration_plan(
        {SettingKey.MEETINGS_DIR: raw},
        AppPreferences(),
        frozenset({SettingKey.MEETINGS_DIR}),
    )
    field = _candidate(plan, Capability.RECORDING_CORE).fields[0]
    replacement = plan.replacement((Capability.RECORDING_CORE,), ())

    assert field.process_present is True
    assert replacement.value_for(PreferenceKey.MEETINGS_DIR) == raw


def _candidate(plan, capability: Capability):
    return next(item for item in plan.candidates if item.capability is capability)


def _minimum_group(capability: Capability) -> dict[SettingKey, str]:
    return {
        Capability.RECORDING_CORE: {SettingKey.MEETINGS_DIR: "/meetings"},
        Capability.TRANSCRIPTION: {SettingKey.ASSEMBLYAI_API_KEY: "assembly-secret"},
        Capability.BACKUP: {
            SettingKey.B2_APPLICATION_KEY_ID: "b2-id",
            SettingKey.B2_APPLICATION_KEY: "b2-secret",
            SettingKey.B2_ENDPOINT: "https://s3.example.invalid",
            SettingKey.B2_REGION: "region",
            SettingKey.B2_BUCKET_NAME: "bucket",
        },
        Capability.CALENDAR: {
            SettingKey.GOOGLE_CALENDAR_CREDENTIALS_FILE: "credentials.json",
        },
        Capability.NOTES: {SettingKey.ANTHROPIC_API_KEY: "notes-secret"},
    }[capability]

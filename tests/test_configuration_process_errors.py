"""Invalid higher-priority process values remain selected and source-correct."""

from __future__ import annotations

from pathlib import Path

import pytest
from configuration_loader_fakes import (
    issue_for,
    load_test_configuration,
    provider_preferences,
    source_for,
    write_env,
)

from meeting_memory.service import readiness
from meeting_memory.types.capabilities import Capability, CapabilityState
from meeting_memory.types.configuration import (
    AppPreferences,
    CapabilityPreference,
    PreferenceKey,
    PreferenceValue,
    SecretId,
    SettingKey,
)
from meeting_memory.types.configuration_resolution import (
    ConfigurationIssueCode,
    ConfigurationUse,
    SettingSource,
)


def test_invalid_partial_process_endpoint_is_attributed_before_valid_app_backup() -> None:
    base, material = provider_preferences(SecretId.BACKUP, enabled=True)
    preferences = AppPreferences(
        values=(
            PreferenceValue(PreferenceKey.B2_ENDPOINT, "https://s3.example.invalid"),
            PreferenceValue(PreferenceKey.B2_REGION, "app-region"),
            PreferenceValue(PreferenceKey.B2_BUCKET_NAME, "app-bucket"),
        ),
        capabilities=base.capabilities,
        secret_refs=base.secret_refs,
    )
    reads = 0

    def read(_ref):
        nonlocal reads
        reads += 1
        return material

    loaded = load_test_configuration(
        ConfigurationUse.READINESS,
        preferences=preferences,
        process={"B2_ENDPOINT": "https://:443"},
        reader=read,
    )

    _assert_process_failure(loaded, Capability.BACKUP, SettingKey.B2_ENDPOINT)
    assert reads == 0


@pytest.mark.parametrize(
    ("capability", "secret_id", "process_key", "process_value"),
    [
        (
            Capability.TRANSCRIPTION,
            SecretId.TRANSCRIPTION,
            SettingKey.ASSEMBLYAI_API_KEY,
            "",
        ),
        (
            Capability.NOTES,
            SecretId.NOTES,
            SettingKey.ANTHROPIC_API_KEY,
            "replace-me",
        ),
    ],
)
def test_invalid_process_secret_masks_valid_app_secret_with_source_correct_action(
    capability: Capability,
    secret_id: SecretId,
    process_key: SettingKey,
    process_value: str,
) -> None:
    preferences, material = provider_preferences(secret_id, enabled=True)
    loaded = load_test_configuration(
        ConfigurationUse.READINESS,
        preferences=preferences,
        process={process_key.value: process_value},
        reader=lambda _ref: material,
    )

    _assert_process_failure(loaded, capability, process_key)


def test_blank_process_calendar_path_masks_valid_app_path(tmp_path: Path) -> None:
    preferences = AppPreferences(
        values=(
            PreferenceValue(
                PreferenceKey.GOOGLE_CALENDAR_CREDENTIALS_FILE,
                str(tmp_path / "app-credentials.json"),
            ),
        ),
        capabilities=(CapabilityPreference(Capability.CALENDAR, True),),
    )
    loaded = load_test_configuration(
        ConfigurationUse.READINESS,
        preferences=preferences,
        process={"GOOGLE_CALENDAR_CREDENTIALS_FILE": " "},
    )

    _assert_process_failure(
        loaded,
        Capability.CALENDAR,
        SettingKey.GOOGLE_CALENDAR_CREDENTIALS_FILE,
    )


@pytest.mark.parametrize(
    ("capability", "process"),
    [
        (Capability.TRANSCRIPTION, {"ASSEMBLYAI_API_KEY": ""}),
        (Capability.NOTES, {"ANTHROPIC_API_KEY": "replace-me"}),
        (Capability.CALENDAR, {"GOOGLE_CALENDAR_CREDENTIALS_FILE": " "}),
        (Capability.BACKUP, {"B2_ENDPOINT": "https://:443"}),
    ],
)
def test_explicit_disable_still_masks_incomplete_invalid_process_group(
    capability: Capability,
    process: dict[str, str],
) -> None:
    preferences = AppPreferences(
        capabilities=(CapabilityPreference(capability, False),),
    )
    loaded = load_test_configuration(
        ConfigurationUse.READINESS,
        preferences=preferences,
        process=process,
    )

    status = _status(loaded, capability)

    assert loaded.capability_enabled(capability) is False
    assert not any(issue.capability is capability for issue in loaded.issues)
    assert status.state is CapabilityState.UNCONFIGURED


def test_blank_process_secret_masks_valid_legacy_without_fallback(tmp_path: Path) -> None:
    loaded = load_test_configuration(
        ConfigurationUse.READINESS,
        env_file=write_env(tmp_path, {"ASSEMBLYAI_API_KEY": "legacy-sentinel"}),
        process={"ASSEMBLYAI_API_KEY": ""},
    )

    _assert_process_failure(
        loaded,
        Capability.TRANSCRIPTION,
        SettingKey.ASSEMBLYAI_API_KEY,
    )
    assert loaded.resolution.value_for(SettingKey.ASSEMBLYAI_API_KEY) == ""


def _assert_process_failure(loaded, capability: Capability, key: SettingKey) -> None:
    issue = issue_for(loaded, capability)
    status = _status(loaded, capability)

    assert loaded.capability_enabled(capability) is False
    assert source_for(loaded, key) is SettingSource.PROCESS_ENV
    assert loaded.process_environment_active(capability) is False
    assert loaded.process_environment_selected(capability) is True
    assert issue.code is ConfigurationIssueCode.EFFECTIVE_CONFIGURATION_INVALID
    assert "process environment" in issue.action.lower()
    assert "app-owned" not in issue.action.lower()
    assert status.state is CapabilityState.FAILED
    assert "Process environment override requires attention." in status.summary


def _status(loaded, capability: Capability):
    report = readiness.build_readiness_report(
        loaded.settings,
        configuration=loaded,
        native_probe=lambda: {"event": "supported", "microphone": "Built-in"},
        durable_probe=lambda _path: None,
        system_name="Darwin",
        kernel_release="24.0.0",
        python_version=(3, 11),
    )
    return report.status_for(capability)

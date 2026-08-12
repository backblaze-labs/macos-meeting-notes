"""Consent-aware readiness mapping for composed source failures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from configuration_loader_fakes import load_test_configuration, provider_preferences

from meeting_memory.service import configuration_sources, readiness
from meeting_memory.service.configuration_loader import load_configuration
from meeting_memory.types.capabilities import Capability, CapabilityState
from meeting_memory.types.configuration import (
    AppPreferences,
    CapabilityPreference,
    PreferenceKey,
    PreferenceSnapshot,
    PreferenceValue,
    SecretId,
)
from meeting_memory.types.configuration_resolution import (
    ConfigurationIssueCode,
    ConfigurationUse,
)


@pytest.mark.parametrize("enabled", [False, True])
def test_masked_unreadable_legacy_env_never_overrides_explicit_consent_state(
    tmp_path: Path,
    monkeypatch,
    enabled: bool,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("legacy content", encoding="utf-8")
    monkeypatch.setattr(configuration_sources, "MAX_LEGACY_ENV_BYTES", 4)
    preferences = AppPreferences(
        capabilities=(CapabilityPreference(Capability.TRANSCRIPTION, enabled),),
    )
    loaded = load_configuration(
        ConfigurationUse.READINESS,
        env_file=env_file,
        process_environment={"MEETINGS_DIR": str(tmp_path / "meetings")},
        preference_reader=lambda: PreferenceSnapshot(preferences, None),
    )

    report = readiness.build_readiness_report(
        loaded.settings,
        configuration=loaded,
        native_probe=lambda: {
            "event": "supported",
            "microphone": "Built-in",
            "microphone_permission": "authorized",
            "system_audio_permission": "authorized",
        },
        durable_probe=lambda _path: None,
        system_name="Darwin",
        kernel_release="24.0.0",
        python_version=(3, 11),
    )
    transcription = report.status_for(Capability.TRANSCRIPTION)
    issue_codes = {
        issue.code for issue in loaded.issues if issue.capability is Capability.TRANSCRIPTION
    }

    assert ConfigurationIssueCode.LEGACY_ENV_UNAVAILABLE not in issue_codes
    if enabled:
        assert transcription.state is CapabilityState.FAILED
        assert ConfigurationIssueCode.APP_CONFIGURATION_INVALID in issue_codes
        assert ".env" not in f"{transcription.summary} {transcription.action}"
    else:
        assert transcription.state is CapabilityState.UNCONFIGURED
        assert issue_codes == set()


def test_complete_process_groups_override_stored_disable_in_runtime_and_readiness(
    tmp_path: Path,
) -> None:
    credentials = tmp_path / "credentials.json"
    credentials.write_text(
        json.dumps(
            {
                "installed": {
                    "client_id": "client",
                    "client_secret": "secret",
                    "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": ["http://localhost"],
                }
            }
        ),
        encoding="utf-8",
    )
    cases = (
        (
            Capability.TRANSCRIPTION,
            {"ASSEMBLYAI_API_KEY": "transcription-sentinel"},
            "transcription",
        ),
        (
            Capability.BACKUP,
            {
                "B2_APPLICATION_KEY_ID": "id-sentinel",
                "B2_APPLICATION_KEY": "key-sentinel",
                "B2_ENDPOINT": "https://s3.example.invalid",
                "B2_REGION": "region",
                "B2_BUCKET_NAME": "bucket",
            },
            "backup",
        ),
        (
            Capability.CALENDAR,
            {"GOOGLE_CALENDAR_CREDENTIALS_FILE": str(credentials)},
            "calendar",
        ),
        (
            Capability.NOTES,
            {
                "ANTHROPIC_API_KEY": "notes-sentinel",
                "SUMMARY_PROMPT_FILE": "",
            },
            "notes",
        ),
    )

    for capability, values, accessor in cases:
        preferences = AppPreferences(
            capabilities=(CapabilityPreference(capability, False),),
        )
        loaded = load_test_configuration(
            ConfigurationUse.READINESS,
            preferences=preferences,
            process={"MEETINGS_DIR": str(tmp_path / capability.value), **values},
        )
        report = _report(loaded, token_reader=_valid_token)
        status = report.status_for(capability)

        assert loaded.capability_enabled(capability) is True
        assert getattr(loaded, accessor) is not None
        assert status.state is CapabilityState.READY
        assert "Process environment override is active." in status.summary
        assert all(sentinel not in status.summary for sentinel in values.values() if sentinel)


def test_partial_process_field_is_reported_for_app_owned_backup(tmp_path: Path) -> None:
    base, material = provider_preferences(SecretId.BACKUP, enabled=True)
    preferences = AppPreferences(
        values=(
            PreferenceValue(PreferenceKey.B2_ENDPOINT, "https://s3.example.invalid"),
            PreferenceValue(PreferenceKey.B2_REGION, "app-region"),
            PreferenceValue(PreferenceKey.B2_BUCKET_NAME, "bucket"),
        ),
        capabilities=base.capabilities,
        secret_refs=base.secret_refs,
    )
    loaded = load_test_configuration(
        ConfigurationUse.READINESS,
        preferences=preferences,
        process={
            "MEETINGS_DIR": str(tmp_path / "meetings"),
            "B2_REGION": "process-region-sentinel",
        },
        reader=lambda _ref: material,
    )

    status = _report(loaded).status_for(Capability.BACKUP)

    assert loaded.backup is not None
    assert loaded.backup.region == "process-region-sentinel"
    assert loaded.capability_for(Capability.BACKUP).process_override is False
    assert loaded.process_environment_active(Capability.BACKUP) is True
    assert status.state is CapabilityState.READY
    assert "Process environment override is active." in status.summary
    assert "process-region-sentinel" not in status.summary


def test_recording_core_reports_process_provenance_without_its_value(tmp_path: Path) -> None:
    meetings = tmp_path / "private-meetings-sentinel"
    loaded = load_test_configuration(
        ConfigurationUse.READINESS,
        process={"MEETINGS_DIR": str(meetings)},
    )

    core = _report(loaded).status_for(Capability.RECORDING_CORE)

    assert "Process environment override is active." in core.summary
    assert str(meetings) not in core.summary


def _report(loaded, *, token_reader=None):
    return readiness.build_readiness_report(
        loaded.settings,
        configuration=loaded,
        token_reader=token_reader,
        native_probe=lambda: {
            "event": "supported",
            "microphone": "Built-in",
            "microphone_permission": "authorized",
            "system_audio_permission": "authorized",
        },
        durable_probe=lambda _path: None,
        system_name="Darwin",
        kernel_release="24.0.0",
        python_version=(3, 11),
    )


def _valid_token() -> str:
    return json.dumps(
        {
            "refresh_token": "token",
            "client_id": "client",
            "client_secret": "secret",
        }
    )

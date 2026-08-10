"""Strict B2 destination validation before process override or adapter use."""

from __future__ import annotations

import pytest
from configuration_loader_fakes import issue_for, load_test_configuration

from meeting_memory.service import readiness
from meeting_memory.service.configuration_loader import load_configuration
from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration import (
    AppPreferences,
    CapabilityPreference,
)
from meeting_memory.types.configuration_resolution import (
    ConfigurationIssueCode,
    ConfigurationUse,
)

MALFORMED_ENDPOINTS = (
    "http://s3.example.invalid",
    "https://[",
    "https://:443",
    "https://user@",
    "https://example.com:bad",
    "https://example.com:0",
    "https://user:pass@example.com",
    "https://example.com/path",
    "https://example.com?query=yes",
    "https://example.com#fragment",
    "https://bad_host.example",
    "https://-bad.example",
)


@pytest.mark.parametrize("endpoint", MALFORMED_ENDPOINTS)
def test_malformed_effective_b2_destination_never_reaches_runtime(endpoint: str) -> None:
    loaded = load_test_configuration(
        ConfigurationUse.RUNTIME,
        process=_backup_process(endpoint),
    )

    assert loaded.backup is None
    issue = issue_for(loaded, Capability.BACKUP)
    assert issue.code is ConfigurationIssueCode.EFFECTIVE_CONFIGURATION_INVALID
    assert issue.blocking is True
    status = _readiness_status(loaded)
    assert "Process environment override requires attention." in status.summary
    assert "override is active" not in status.summary
    assert endpoint not in status.summary


@pytest.mark.parametrize(
    "endpoint",
    ["https://s3.example.invalid", "https://s3.example.invalid:443/"],
)
def test_valid_b2_https_origins_remain_compatible(endpoint: str) -> None:
    loaded = load_test_configuration(
        ConfigurationUse.RUNTIME,
        process=_backup_process(endpoint),
    )

    assert loaded.backup is not None
    assert loaded.backup.endpoint == endpoint


@pytest.mark.parametrize("endpoint", MALFORMED_ENDPOINTS)
def test_malformed_process_group_never_overrides_explicit_disable(endpoint: str) -> None:
    preferences = AppPreferences(
        capabilities=(CapabilityPreference(Capability.BACKUP, False),),
    )
    loaded = load_test_configuration(
        ConfigurationUse.RUNTIME,
        preferences=preferences,
        process=_backup_process(endpoint),
    )

    backup = loaded.capability_for(Capability.BACKUP)
    assert backup.process_override is False
    assert backup.enabled is False
    assert loaded.backup is None


@pytest.mark.parametrize("endpoint", MALFORMED_ENDPOINTS)
def test_malformed_process_group_never_reopens_corrupt_preferences(endpoint: str) -> None:
    loaded = load_configuration(
        ConfigurationUse.RUNTIME,
        env_file=None,
        process_environment=_backup_process(endpoint),
        preference_reader=lambda: (_ for _ in ()).throw(RuntimeError("sentinel")),
    )

    backup = loaded.capability_for(Capability.BACKUP)
    assert backup.process_override is False
    assert backup.enabled is False
    assert loaded.backup is None
    issue = issue_for(loaded, Capability.BACKUP)
    assert issue.code is ConfigurationIssueCode.PREFERENCES_UNAVAILABLE
    assert issue.blocking is True


def _backup_process(endpoint: str) -> dict[str, str]:
    return {
        "B2_APPLICATION_KEY_ID": "id",
        "B2_APPLICATION_KEY": "secret",
        "B2_ENDPOINT": endpoint,
        "B2_REGION": "region",
        "B2_BUCKET_NAME": "bucket",
    }


def _readiness_status(loaded):
    report = readiness.build_readiness_report(
        loaded.settings,
        configuration=loaded,
        native_probe=lambda: {"event": "supported", "microphone": "Built-in"},
        durable_probe=lambda _path: None,
        system_name="Darwin",
        kernel_release="24.0.0",
        python_version=(3, 11),
    )
    return report.status_for(Capability.BACKUP)

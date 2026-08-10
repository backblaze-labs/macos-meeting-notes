"""Bounded source I/O and legacy-parity tests for Stage 4B composition."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from configuration_loader_fakes import issue_for, load_test_configuration

from meeting_memory.config.resolution import resolve_configuration
from meeting_memory.config.runtime import RuntimeSettings
from meeting_memory.service import configuration_sources
from meeting_memory.service.configuration_loader import (
    ConfigurationLoadError,
)
from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration import AppPreferences, SettingKey
from meeting_memory.types.configuration_resolution import (
    ConfigurationIssueCode,
    ConfigurationUse,
    SettingSource,
)


@pytest.mark.parametrize("kind", ["fifo", "oversize"])
def test_unbounded_or_nonregular_legacy_env_fails_locally_without_hanging(
    tmp_path: Path,
    monkeypatch,
    kind: str,
) -> None:
    env_file = tmp_path / ".env"
    if kind == "fifo":
        os.mkfifo(env_file)
    else:
        monkeypatch.setattr(configuration_sources, "MAX_LEGACY_ENV_BYTES", 4)
        env_file.write_text("MEETINGS_DIR=/private", encoding="utf-8")

    loaded = load_test_configuration(
        ConfigurationUse.RUNTIME,
        env_file=env_file,
    )

    assert loaded.meetings_dir_path
    assert loaded.transcription is None
    issue = issue_for(loaded, Capability.TRANSCRIPTION)
    assert issue.code is ConfigurationIssueCode.LEGACY_ENV_UNAVAILABLE
    assert issue.blocking is True


def test_regular_legacy_env_symlink_is_read_only_and_preserved(tmp_path: Path) -> None:
    target = tmp_path / "legacy.env"
    linked = tmp_path / ".env"
    meetings = tmp_path / "linked-meetings"
    original = f"MEETINGS_DIR={meetings}\n".encode()
    target.write_bytes(original)
    linked.symlink_to(target)

    loaded = load_test_configuration(ConfigurationUse.SEARCH, env_file=linked)

    assert loaded.meetings_dir_path == meetings
    assert linked.is_symlink()
    assert linked.readlink() == target
    assert target.read_bytes() == original


def test_legacy_env_device_is_rejected_with_sanitized_capability_issue() -> None:
    loaded = load_test_configuration(
        ConfigurationUse.RUNTIME,
        env_file=Path("/dev/null"),
    )

    issue = issue_for(loaded, Capability.TRANSCRIPTION)
    assert issue.code is ConfigurationIssueCode.LEGACY_ENV_UNAVAILABLE
    assert issue.blocking is True
    assert "/dev/null" not in repr(loaded)


def test_dotenv_interpolation_never_reads_live_process_environment(
    tmp_path: Path,
    monkeypatch,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("MEETINGS_DIR=${AMBIENT_SENTINEL}\n", encoding="utf-8")
    monkeypatch.setenv("AMBIENT_SENTINEL", "/ambient/private")

    loaded = load_test_configuration(
        ConfigurationUse.SEARCH,
        env_file=env_file,
        process={},
    )

    assert loaded.meetings_dir_path != Path("/ambient/private")
    assert "AMBIENT_SENTINEL" in str(loaded.meetings_dir_path)


def test_blank_core_path_remains_selected_without_default_fallback() -> None:
    result = resolve_configuration(
        process_environment={"MEETINGS_DIR": ""},
        preferences=AppPreferences(),
        app_secrets=(),
        legacy_environment={"MEETINGS_DIR": "/legacy/meetings"},
    )

    assert result.value_for(SettingKey.MEETINGS_DIR) == ""
    provenance = next(item for item in result.provenance if item.key is SettingKey.MEETINGS_DIR)
    assert provenance.source is SettingSource.PROCESS_ENV


def test_missing_app_preferences_preserve_all_legacy_provider_groups(
    tmp_path: Path,
    monkeypatch,
) -> None:
    for key in SettingKey:
        monkeypatch.delenv(key.value, raising=False)
        monkeypatch.delenv(key.value.lower(), raising=False)
    credentials = tmp_path / "credentials.json"
    prompt = tmp_path / "prompt.md"
    env_file = tmp_path / ".env"
    original = (
        f"MEETINGS_DIR={tmp_path / 'meetings'}\n"
        "ASSEMBLYAI_API_KEY=assembly-secret\n"
        "B2_APPLICATION_KEY_ID=b2-id\n"
        "B2_APPLICATION_KEY=b2-secret\n"
        "B2_ENDPOINT=https://s3.example.invalid\n"
        "B2_REGION=region\n"
        "B2_BUCKET_NAME=bucket\n"
        f"GOOGLE_CALENDAR_CREDENTIALS_FILE={credentials}\n"
        "GOOGLE_CALENDAR_ID=primary\n"
        "ANTHROPIC_API_KEY=notes-secret\n"
        "ANTHROPIC_MODEL=model\n"
        f"SUMMARY_PROMPT_FILE={prompt}\n"
    ).encode()
    env_file.write_bytes(original)

    legacy = RuntimeSettings(_env_file=env_file)
    loaded = load_test_configuration(ConfigurationUse.RUNTIME, env_file=env_file)

    for field_name in RuntimeSettings.model_fields:
        assert getattr(loaded.settings, field_name) == getattr(legacy, field_name)
    assert loaded.transcription is not None
    assert loaded.backup is not None
    assert loaded.calendar is not None
    assert loaded.notes is not None
    assert env_file.read_bytes() == original


@pytest.mark.parametrize("content", [b"MEETINGS_DIR\n", b"MEETINGS_DIR=\n"])
def test_blank_legacy_meetings_dir_never_falls_back_to_cwd(
    tmp_path: Path,
    content: bytes,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_bytes(content)

    with pytest.raises(ConfigurationLoadError) as error:
        load_test_configuration(ConfigurationUse.SEARCH, env_file=env_file)

    assert str(tmp_path) not in str(error.value)
    assert env_file.read_bytes() == content


def test_blank_process_meetings_dir_masks_legacy_and_fails_sanitized(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env"
    original = b"MEETINGS_DIR=/legacy/meetings\n"
    env_file.write_bytes(original)

    with pytest.raises(ConfigurationLoadError) as error:
        load_test_configuration(
            ConfigurationUse.RUNTIME,
            env_file=env_file,
            process={"MEETINGS_DIR": ""},
        )

    assert "legacy/meetings" not in str(error.value)
    assert str(Path.cwd()) not in str(error.value)
    assert env_file.read_bytes() == original

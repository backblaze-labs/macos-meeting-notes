"""Effective path resolution must never inherit the process cwd."""

from __future__ import annotations

from pathlib import Path

import pytest

from meeting_memory.service.configuration_loader import (
    ConfigurationLoadError,
    load_configuration,
)
from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration import (
    AppPreferences,
    CapabilityPreference,
    PreferenceKey,
    PreferenceSnapshot,
    PreferenceValue,
)
from meeting_memory.types.configuration_resolution import ConfigurationUse
from meeting_memory.types.runtime_layout import RuntimeLayout


def test_selected_legacy_paths_follow_env_parent_across_cwd_changes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "legacy" / ".env"
    source.parent.mkdir()
    source.write_text(
        "MEETINGS_DIR=./meetings\n"
        "GOOGLE_CALENDAR_CREDENTIALS_FILE=./oauth/client.json\n"
        "GOOGLE_CALENDAR_ID=all\n"
        "ANTHROPIC_API_KEY=notes-secret\n"
        "SUMMARY_PROMPT_FILE=./prompts/private.md\n",
        encoding="utf-8",
    )
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    monkeypatch.chdir(foreign)
    layout = RuntimeLayout.bundled(tmp_path / "Meeting Memory.app", home=tmp_path / "home")

    loaded = load_configuration(
        ConfigurationUse.RUNTIME,
        env_file=source,
        process_environment={},
        preference_reader=lambda: PreferenceSnapshot(AppPreferences(), None),
        runtime_layout=layout,
    )
    monkeypatch.chdir(tmp_path)

    assert loaded.meetings_dir_path == source.parent / "meetings"
    assert loaded.calendar is not None
    assert loaded.calendar.credentials_file == source.parent / "oauth" / "client.json"
    assert loaded.notes is not None
    assert loaded.notes.prompt_file == source.parent / "prompts" / "private.md"


def test_relative_app_preference_anchors_to_application_support(tmp_path: Path) -> None:
    layout = RuntimeLayout.bundled(tmp_path / "Meeting Memory.app", home=tmp_path / "home")
    preferences = AppPreferences(
        values=(
            PreferenceValue(
                PreferenceKey.GOOGLE_CALENDAR_CREDENTIALS_FILE,
                "oauth/client.json",
            ),
        ),
        capabilities=(CapabilityPreference(Capability.CALENDAR, True),),
    )

    loaded = load_configuration(
        ConfigurationUse.RUNTIME,
        env_file=None,
        process_environment={},
        preference_reader=lambda: PreferenceSnapshot(preferences, "a" * 64),
        runtime_layout=layout,
    )

    assert loaded.calendar is not None
    assert loaded.calendar.credentials_file == layout.application_support / "oauth/client.json"


def test_checkout_default_prompt_is_personal_application_support_state(tmp_path: Path) -> None:
    layout = RuntimeLayout.development(tmp_path / "checkout", home=tmp_path / "home")

    loaded = load_configuration(
        ConfigurationUse.RUNTIME,
        env_file=None,
        process_environment={"ANTHROPIC_API_KEY": "notes-secret"},
        preference_reader=lambda: PreferenceSnapshot(AppPreferences(), None),
        runtime_layout=layout,
    )

    assert loaded.notes is not None
    assert loaded.notes.prompt_file == (
        layout.application_support / "prompts" / "summary.md"
    )


def test_checkout_legacy_scaffold_prompt_upgrades_to_personal_state(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    source = checkout / ".env"
    source.write_text(
        "ANTHROPIC_API_KEY=notes-secret\n"
        "SUMMARY_PROMPT_FILE=prompts/summary.md\n",
        encoding="utf-8",
    )
    layout = RuntimeLayout.development(checkout, home=tmp_path / "home")

    loaded = load_configuration(
        ConfigurationUse.RUNTIME,
        env_file=source,
        process_environment={},
        preference_reader=lambda: PreferenceSnapshot(AppPreferences(), None),
        runtime_layout=layout,
    )

    assert loaded.notes is not None
    assert loaded.notes.prompt_file == (
        layout.application_support / "prompts" / "summary.md"
    )


def test_bundled_relative_process_path_blocks_only_optional_capability(tmp_path: Path) -> None:
    layout = RuntimeLayout.bundled(tmp_path / "Meeting Memory.app", home=tmp_path / "home")

    loaded = load_configuration(
        ConfigurationUse.RUNTIME,
        env_file=None,
        process_environment={"GOOGLE_CALENDAR_CREDENTIALS_FILE": "private-sentinel.json"},
        preference_reader=lambda: PreferenceSnapshot(AppPreferences(), None),
        runtime_layout=layout,
    )

    assert loaded.calendar is None
    issue = next(item for item in loaded.issues if item.capability is Capability.CALENDAR)
    assert issue.blocking is True
    assert "private-sentinel" not in repr(issue)


def test_bundled_relative_process_meetings_path_fails_core_safely(tmp_path: Path) -> None:
    layout = RuntimeLayout.bundled(tmp_path / "Meeting Memory.app", home=tmp_path / "home")

    with pytest.raises(ConfigurationLoadError, match="Recording Core") as failure:
        load_configuration(
            ConfigurationUse.RUNTIME,
            env_file=None,
            process_environment={"MEETINGS_DIR": "private-sentinel"},
            preference_reader=lambda: PreferenceSnapshot(AppPreferences(), None),
            runtime_layout=layout,
        )

    assert "private-sentinel" not in str(failure.value)

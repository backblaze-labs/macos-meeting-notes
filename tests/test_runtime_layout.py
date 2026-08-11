"""Pure runtime-layout contracts for checkout and frozen app execution."""

from __future__ import annotations

from pathlib import Path

import pytest

from meeting_memory.types.configuration import SettingKey
from meeting_memory.types.configuration_resolution import SettingSource
from meeting_memory.types.runtime_layout import (
    RelativeRuntimePathError,
    RuntimeLayout,
    RuntimeMode,
)


def test_development_layout_anchors_paths_without_consulting_cwd(tmp_path: Path) -> None:
    project = tmp_path / "checkout"
    home = tmp_path / "home"
    legacy = tmp_path / "profile" / ".env"
    layout = RuntimeLayout.development(project, home=home)

    assert layout.mode is RuntimeMode.CHECKOUT
    assert layout.legacy_env_path == project / ".env"
    assert layout.legacy_source_path() == project / ".env"
    assert layout.native_helper_path == project / ".build" / "MeetingMemoryCapture"
    assert (
        layout.resolve_setting_path(
            SettingKey.GOOGLE_CALENDAR_CREDENTIALS_FILE,
            Path("oauth/client.json"),
            SettingSource.PROCESS_ENV,
        )
        == project / "oauth" / "client.json"
    )
    assert (
        layout.resolve_setting_path(
            SettingKey.SUMMARY_PROMPT_FILE,
            Path("prompts/custom.md"),
            SettingSource.LEGACY_ENV,
            legacy_env_path=legacy,
        )
        == legacy.parent / "prompts" / "custom.md"
    )
    assert (
        layout.resolve_setting_path(
            SettingKey.SUMMARY_PROMPT_FILE,
            Path("prompts/managed.md"),
            SettingSource.APP_PREFERENCE,
        )
        == home / "Library/Application Support/meeting-memory/prompts/managed.md"
    )


def test_bundled_layout_uses_only_bundle_and_user_support_roots(tmp_path: Path) -> None:
    bundle = tmp_path / "Meeting Memory.app"
    home = tmp_path / "home"
    layout = RuntimeLayout.bundled(bundle, home=home)

    support = home / "Library" / "Application Support" / "meeting-memory"
    assert layout.mode is RuntimeMode.BUNDLED
    assert layout.legacy_env_path is None
    assert layout.legacy_source_path() is None
    assert layout.application_support == support
    assert layout.native_helper_path == (bundle / "Contents" / "MacOS" / "MeetingMemoryCapture")
    assert layout.default_prompt_path == support / "prompts" / "summary.md"
    assert layout.default_credentials_path == support / "credentials.json"

    with pytest.raises(RelativeRuntimePathError, match="absolute"):
        layout.legacy_source_path(Path("old/.env"))
    assert layout.legacy_source_path(tmp_path / "selected.env") == tmp_path / "selected.env"


def test_bundled_layout_rejects_ambiguous_relative_process_paths(tmp_path: Path) -> None:
    layout = RuntimeLayout.bundled(tmp_path / "Meeting Memory.app", home=tmp_path / "home")

    with pytest.raises(RelativeRuntimePathError, match="absolute"):
        layout.resolve_setting_path(
            SettingKey.GOOGLE_CALENDAR_CREDENTIALS_FILE,
            Path("private-sentinel.json"),
            SettingSource.PROCESS_ENV,
        )
    assert (
        layout.resolve_setting_path(
            SettingKey.GOOGLE_CALENDAR_CREDENTIALS_FILE,
            Path("oauth/managed.json"),
            SettingSource.APP_PREFERENCE,
        )
        == layout.application_support / "oauth/managed.json"
    )


def test_bundled_layout_anchors_selected_legacy_and_defaults(tmp_path: Path) -> None:
    layout = RuntimeLayout.bundled(tmp_path / "Meeting Memory.app", home=tmp_path / "home")
    selected_env = tmp_path / "old-checkout" / ".env"

    assert (
        layout.resolve_setting_path(
            SettingKey.MEETINGS_DIR,
            Path("recordings"),
            SettingSource.LEGACY_ENV,
            legacy_env_path=selected_env,
        )
        == selected_env.parent / "recordings"
    )
    assert (
        layout.resolve_setting_path(
            SettingKey.SUMMARY_PROMPT_FILE,
            Path("prompts/summary.md"),
            SettingSource.DEFAULT,
        )
        == layout.default_prompt_path
    )


def test_layout_rejects_non_path_setting_keys(tmp_path: Path) -> None:
    layout = RuntimeLayout.development(tmp_path / "checkout", home=tmp_path / "home")

    with pytest.raises(ValueError, match="path-valued"):
        layout.resolve_setting_path(
            SettingKey.ANTHROPIC_MODEL,
            Path("model"),
            SettingSource.DEFAULT,
        )


def test_layout_expands_home_from_captured_root_and_rejects_named_users(
    tmp_path: Path,
) -> None:
    layout = RuntimeLayout.development(tmp_path / "checkout", home=tmp_path / "home")

    assert layout.resolve_checkout_path("~/helper") == tmp_path / "home/helper"
    with pytest.raises(RelativeRuntimePathError, match="named-user"):
        layout.resolve_checkout_path("~someone/helper")


def test_app_owned_relative_path_cannot_escape_application_support(tmp_path: Path) -> None:
    layout = RuntimeLayout.bundled(tmp_path / "Meeting Memory.app", home=tmp_path / "home")

    with pytest.raises(RelativeRuntimePathError, match="app storage"):
        layout.resolve_setting_path(
            SettingKey.SUMMARY_PROMPT_FILE,
            "../../private-sentinel.md",
            SettingSource.APP_PREFERENCE,
        )

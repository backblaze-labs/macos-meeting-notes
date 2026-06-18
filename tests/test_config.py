"""Tests for settings loading and fail-fast validation."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from meeting_memory.config.defaults import REQUIRED_ENV_VARS
from meeting_memory.config.settings import Settings, load_settings, validate_or_exit

OPTIONAL_ENV_VARS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_MODEL",
    "SUMMARY_PROMPT_FILE",
    "SPEAKER_MAPPING_FILE",
    "GOOGLE_CALENDAR_CREDENTIALS_FILE",
    "GOOGLE_CALENDAR_ID",
    "MEETINGS_DIR",
    "AUDIO_DEVICE",
    "NOTIFY_MINUTES_BEFORE",
    "MAX_RECORDING_MINUTES",
    "CALENDAR_POLL_INTERVAL",
)


@pytest.fixture(autouse=True)
def clear_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (*REQUIRED_ENV_VARS, *OPTIONAL_ENV_VARS):
        monkeypatch.delenv(key, raising=False)


def test_load_settings_from_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "B2_APPLICATION_KEY_ID=key-id",
                "B2_APPLICATION_KEY=secret-key",
                "B2_ENDPOINT=https://s3.us-west-004.backblazeb2.com",
                "B2_REGION=us-west-004",
                "B2_BUCKET_NAME=meeting-memory",
                "ASSEMBLYAI_API_KEY=assembly-key",
                "ANTHROPIC_API_KEY=",
                "SUMMARY_PROMPT_FILE=prompts/custom-summary.md",
                "SPEAKER_MAPPING_FILE=speakers.json",
                "MEETINGS_DIR=~/Meeting Archive",
                "NOTIFY_MINUTES_BEFORE=7",
            ]
        ),
        encoding="utf-8",
    )

    settings = load_settings(env_file)

    assert settings.b2_bucket_name == "meeting-memory"
    assert settings.anthropic_api_key is None
    assert settings.anthropic_model == "claude-haiku-4-5"
    assert settings.summary_prompt_file == Path("prompts/custom-summary.md")
    assert settings.speaker_mapping_file == Path("speakers.json")
    assert settings.speaker_mapping_path == Path("speakers.json")
    assert settings.google_calendar_id == "all"
    assert settings.notify_minutes_before == 7
    assert settings.meetings_dir_path == Path("~/Meeting Archive").expanduser()


def test_settings_reject_missing_required_values(tmp_path: Path) -> None:
    with pytest.raises(ValidationError) as exc_info:
        load_settings(tmp_path / "missing.env")

    assert "b2_application_key_id" in str(exc_info.value)
    assert "assemblyai_api_key" in str(exc_info.value)


def test_settings_reject_placeholder_required_values() -> None:
    with pytest.raises(ValidationError, match="non-placeholder"):
        Settings(
            b2_application_key_id="replace-me",
            b2_application_key="secret-key",
            b2_endpoint="https://example.com",
            b2_region="us-west-004",
            b2_bucket_name="meeting-memory",
            assemblyai_api_key="assembly-key",
        )


def test_validate_or_exit_reports_clear_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        validate_or_exit(tmp_path / "missing.env")

    assert exc_info.value.code == 2
    assert "Configuration is invalid" in capsys.readouterr().err

"""Tests for preferences helpers."""

from __future__ import annotations

from pathlib import Path

from meeting_memory.config.settings import Settings
from meeting_memory.ui.preferences import (
    parse_preferences_text,
    preferences_text,
    update_env_file,
)


def test_preferences_text_contains_supported_settings() -> None:
    settings = Settings(
        b2_application_key_id="key-id",
        b2_application_key="secret",
        b2_endpoint="https://s3.example.com",
        b2_region="us-west-004",
        b2_bucket_name="bucket",
        assemblyai_api_key="assembly-key",
        meetings_dir=Path("~/Meetings"),
        notify_minutes_before=7,
        max_recording_minutes=90,
        audio_device="Meeting Aggregate",
    )

    assert preferences_text(settings).splitlines() == [
        "MEETINGS_DIR=~/Meetings",
        "NOTIFY_MINUTES_BEFORE=7",
        "MAX_RECORDING_MINUTES=90",
        "AUDIO_DEVICE=Meeting Aggregate",
    ]


def test_parse_preferences_text_filters_unknown_keys() -> None:
    assert parse_preferences_text("MEETINGS_DIR=/tmp\nUNKNOWN=x\nAUDIO_DEVICE=Mic\n") == {
        "MEETINGS_DIR": "/tmp",
        "AUDIO_DEVICE": "Mic",
    }


def test_update_env_file_replaces_and_appends_preferences(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("B2_BUCKET_NAME=bucket\nMEETINGS_DIR=old\n", encoding="utf-8")

    update_env_file(
        env_path,
        {
            "MEETINGS_DIR": "/tmp/meetings",
            "AUDIO_DEVICE": "Meeting Aggregate",
        },
    )

    assert env_path.read_text(encoding="utf-8").splitlines() == [
        "B2_BUCKET_NAME=bucket",
        "MEETINGS_DIR=/tmp/meetings",
        "AUDIO_DEVICE=Meeting Aggregate",
    ]

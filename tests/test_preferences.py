"""Tests for preferences helpers."""

from __future__ import annotations

from pathlib import Path

from meeting_memory.config.settings import Settings
from meeting_memory.types.speakers import KnownSpeaker
from meeting_memory.ui.preferences import (
    known_speakers_env_value,
    known_speakers_text,
    open_known_speakers_window,
    parse_known_speakers_text,
    parse_preferences_text,
    preferences_text,
    update_env_file,
)


def test_preferences_text_contains_supported_settings() -> None:
    settings = Settings(
        _env_file=None,
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


def test_known_speakers_text_uses_one_speaker_per_line() -> None:
    settings = _settings(
        known_speakers=(
            KnownSpeaker("Alex", ("alex", "eduardo@example.com")),
            KnownSpeaker("Blair", ("blair",)),
            KnownSpeaker("Casey"),
        )
    )

    assert known_speakers_text(settings).splitlines() == [
        "Alex: alex, eduardo@example.com",
        "Blair: blair",
        "Casey",
    ]


def test_parse_known_speakers_text_accepts_friendly_lines() -> None:
    speakers = parse_known_speakers_text(
        """
        Alex: alex, eduardo@example.com
        Blair: blair
        Casey
        # comments are ignored
        """
    )

    assert speakers == (
        KnownSpeaker("Alex", ("alex", "eduardo@example.com")),
        KnownSpeaker("Blair", ("blair",)),
        KnownSpeaker("Casey"),
    )


def test_parse_known_speakers_text_accepts_json_and_legacy_csv() -> None:
    assert parse_known_speakers_text('{"Alex":["alex"]}') == (
        KnownSpeaker("Alex", ("alex",)),
    )
    assert parse_known_speakers_text("Alex=alex,Blair=blair") == (
        KnownSpeaker("Alex", ("alex",)),
        KnownSpeaker("Blair", ("blair",)),
    )


def test_known_speakers_env_value_writes_compact_json() -> None:
    assert (
        known_speakers_env_value(
            (
                KnownSpeaker("Alex", ("alex",)),
                KnownSpeaker("Blair", ("blair",)),
            )
        )
        == '{"Alex":["alex"],"Blair":["blair"]}'
    )


def test_open_known_speakers_window_updates_env_file(tmp_path: Path, monkeypatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("B2_BUCKET_NAME=bucket\nKNOWN_SPEAKERS={}\n", encoding="utf-8")
    fake_rumps = FakeRumps("Alex: alex\nBlair: blair")
    monkeypatch.setattr(
        "meeting_memory.ui.preferences._load_rumps",
        lambda: fake_rumps,
    )

    saved = open_known_speakers_window(_settings(), env_path)

    assert saved is True
    assert env_path.read_text(encoding="utf-8").splitlines() == [
        "B2_BUCKET_NAME=bucket",
        'KNOWN_SPEAKERS={"Alex":["alex"],"Blair":["blair"]}',
    ]
    assert fake_rumps.alerts == ["Known speakers saved. Restart Meeting Memory to apply changes."]


def _settings(
    *,
    known_speakers: tuple[KnownSpeaker, ...] = (),
) -> Settings:
    return Settings(
        _env_file=None,
        b2_application_key_id="key-id",
        b2_application_key="secret",
        b2_endpoint="https://s3.example.com",
        b2_region="us-west-004",
        b2_bucket_name="bucket",
        assemblyai_api_key="assembly-key",
        known_speakers=known_speakers,
    )


class FakeRumps:
    def __init__(self, text: str, *, clicked: bool = True):
        self.text = text
        self.clicked = clicked
        self.alerts: list[str] = []

    def Window(self, **kwargs):
        self.window_kwargs = kwargs
        return FakeWindow(clicked=self.clicked, text=self.text)

    def alert(self, message: str) -> None:
        self.alerts.append(message)


class FakeWindow:
    def __init__(self, *, clicked: bool, text: str):
        self.clicked = clicked
        self.text = text

    def run(self):
        return self

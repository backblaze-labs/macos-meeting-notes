"""Tests for preferences helpers."""

from __future__ import annotations

from pathlib import Path

from meeting_memory.config.settings import Settings
from meeting_memory.types.speakers import KnownSpeaker
from meeting_memory.ui.preference_forms import speakers_from_form_rows
from meeting_memory.ui.preferences import (
    known_speakers_env_value,
    known_speakers_text,
    open_known_speakers_window,
    open_preferences_window,
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
    )

    assert preferences_text(settings).splitlines() == [
        "# Meetings folder (MEETINGS_DIR)",
        "# Where recordings, transcripts, and notes are saved.",
        "MEETINGS_DIR=~/Meetings",
        "",
        "# Reminder (minutes) (NOTIFY_MINUTES_BEFORE)",
        "# How early to remind you before Calendar meetings.",
        "NOTIFY_MINUTES_BEFORE=7",
        "",
        "# Recording limit (minutes) (MAX_RECORDING_MINUTES)",
        "# Maximum recording length before the app stops automatically.",
        "MAX_RECORDING_MINUTES=90",
    ]
    assert "Use:" not in preferences_text(settings)
    assert "Good:" not in preferences_text(settings)
    assert "From:" not in preferences_text(settings)
    assert "safe" not in preferences_text(settings)
    assert "works well" not in preferences_text(settings)


def test_parse_preferences_text_filters_unknown_keys() -> None:
    assert parse_preferences_text("MEETINGS_DIR=/tmp\nUNKNOWN=x\nAUDIO_DEVICE=Mic\n") == {
        "MEETINGS_DIR": "/tmp"
    }


def test_update_env_file_replaces_and_appends_preferences(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("B2_BUCKET_NAME=bucket\nMEETINGS_DIR=old\n", encoding="utf-8")

    update_env_file(
        env_path,
        {
            "MEETINGS_DIR": "/tmp/meetings",
            "NOTIFY_MINUTES_BEFORE": "4",
        },
    )

    assert env_path.read_text(encoding="utf-8").splitlines() == [
        "B2_BUCKET_NAME=bucket",
        "MEETINGS_DIR=/tmp/meetings",
        "NOTIFY_MINUTES_BEFORE=4",
    ]


def test_known_speakers_text_uses_one_speaker_per_line() -> None:
    settings = _settings(
        known_speakers=(
            KnownSpeaker("Alex", ("alex", "alex@example.com")),
            KnownSpeaker("Blair", ("blair",)),
            KnownSpeaker("Casey"),
        )
    )

    assert known_speakers_text(settings).splitlines() == [
        "Alex | alex, alex@example.com",
        "Blair | blair",
        "Casey |",
    ]


def test_parse_known_speakers_text_accepts_friendly_lines() -> None:
    speakers = parse_known_speakers_text(
        """
        Alex | alex, alex@example.com
        Blair | blair
        Casey |
        # comments are ignored
        """
    )

    assert speakers == (
        KnownSpeaker("Alex", ("alex", "alex@example.com")),
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


def test_known_speakers_form_rows_use_separate_alias_and_source_fields() -> None:
    assert speakers_from_form_rows(
        [
            ("Alex", "alex, alex@example.com"),
            ("Blair", "blair"),
            ("", "ignored@example.com"),
            ("Alex", "duplicate@example.com"),
        ]
    ) == (
        KnownSpeaker("Alex", ("alex", "alex@example.com")),
        KnownSpeaker("Blair", ("blair",)),
    )


def test_open_preferences_window_updates_env_file_from_form(
    tmp_path: Path,
    monkeypatch,
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("B2_BUCKET_NAME=bucket\nMEETINGS_DIR=old\n", encoding="utf-8")
    fake_rumps = FakeRumps("")
    monkeypatch.setattr("meeting_memory.ui.preferences._load_rumps", lambda: fake_rumps)
    monkeypatch.setattr(
        "meeting_memory.ui.preferences.open_preferences_form",
        lambda _fields: {
            "MEETINGS_DIR": "/tmp/meetings",
            "NOTIFY_MINUTES_BEFORE": "3",
        },
    )

    saved = open_preferences_window(_settings(), env_path)

    assert saved is True
    assert env_path.read_text(encoding="utf-8").splitlines() == [
        "B2_BUCKET_NAME=bucket",
        "MEETINGS_DIR=/tmp/meetings",
        "NOTIFY_MINUTES_BEFORE=3",
    ]
    assert fake_rumps.alerts == ["Preferences saved. Restart Meeting Memory to apply changes."]


def test_open_known_speakers_window_updates_env_file(tmp_path: Path, monkeypatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("B2_BUCKET_NAME=bucket\nKNOWN_SPEAKERS={}\n", encoding="utf-8")
    fake_rumps = FakeRumps("Alex | alex\nBlair | blair")
    monkeypatch.setattr(
        "meeting_memory.ui.preferences.open_known_speakers_form",
        lambda _speakers: (_ for _ in ()).throw(RuntimeError("no AppKit")),
    )
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

from pathlib import Path

import pytest

from meeting_memory.config.runtime import RuntimeSettings, load_runtime_settings
from meeting_memory.service.recorder import RecorderService
from meeting_memory.service.summary_prompt import summary_prompt_path


def test_fresh_runtime_has_core_and_no_optional_capabilities(tmp_path: Path) -> None:
    settings = load_runtime_settings(tmp_path / "missing.env")

    assert settings.meetings_dir_path
    assert settings.transcription is None
    assert settings.backup is None
    assert settings.calendar is None
    assert settings.notes is None


def test_optional_groups_are_independent_and_require_complete_values() -> None:
    settings = RuntimeSettings(
        assemblyai_api_key="assembly-key",
        b2_application_key_id="partial-only",
        google_calendar_credentials_file="calendar.json",
        anthropic_api_key="notes-key",
    )

    assert settings.transcription is not None
    assert settings.backup is None
    assert settings.calendar is not None
    assert settings.notes is not None


def test_complete_legacy_b2_environment_is_an_opt_in() -> None:
    settings = RuntimeSettings(
        b2_application_key_id="id",
        b2_application_key="key",
        b2_endpoint="https://s3.example.invalid",
        b2_region="us-west-004",
        b2_bucket_name="bucket",
    )

    assert settings.backup is not None
    assert settings.backup.bucket_name == "bucket"


def test_runtime_settings_support_the_native_notes_prompt_editor(tmp_path: Path) -> None:
    prompt = tmp_path / "notes-prompt.md"
    settings = RuntimeSettings(summary_prompt_file=prompt)

    assert settings.summary_prompt_path == prompt
    assert summary_prompt_path(settings) == prompt


def test_invalid_optional_values_disable_only_their_capability(tmp_path: Path) -> None:
    settings = RuntimeSettings(
        meetings_dir=tmp_path / "meetings",
        assemblyai_api_key="assembly-key",
        google_calendar_credentials_file="calendar.json",
        calendar_poll_interval=0,
        notify_minutes_before="invalid",
        anthropic_api_key="notes-key",
        anthropic_model=" ",
        known_speakers="{invalid-json",
    )

    assert settings.meetings_dir_path == (tmp_path / "meetings").resolve()
    assert settings.transcription is not None
    assert settings.calendar is None
    assert settings.notes is None
    assert settings.known_speakers == ()


def test_invalid_optional_env_does_not_raise_global_validation(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "MEETINGS_DIR=./meetings\n"
        "GOOGLE_CALENDAR_CREDENTIALS_FILE=calendar.json\n"
        "CALENDAR_POLL_INTERVAL=0\n"
        "ANTHROPIC_API_KEY=notes-key\n"
        "ANTHROPIC_MODEL=\n",
        encoding="utf-8",
    )

    settings = load_runtime_settings(env_file)

    assert settings.max_recording_minutes > 0
    assert settings.calendar is None
    assert settings.notes is None


def test_configured_meetings_root_symlink_is_canonicalized_before_capture(
    tmp_path: Path,
) -> None:
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    configured = tmp_path / "meetings-link"
    configured.symlink_to(canonical, target_is_directory=True)
    settings = RuntimeSettings(meetings_dir=configured)
    seen: list[Path] = []

    def fail_after_empty_source(_mode: str, path: Path):
        seen.append(path)
        raise RuntimeError("capture unavailable")

    recorder = RecorderService(
        temp_dir=settings.meetings_dir_path / ".meeting-memory-staging" / "recordings",
        capture_starter=fail_after_empty_source,
    )

    with pytest.raises(RuntimeError, match="capture unavailable"):
        recorder.start("Symlink Root")

    assert settings.meetings_dir_path == canonical
    assert len(seen) == 1
    assert seen[0].is_relative_to(canonical)

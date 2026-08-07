"""Legacy coupling that Phase 2 intentionally replaces.

These passing characterization tests are removal guides, not endorsements of
the current behavior. Delete or rewrite each test when runtime capabilities are
made independent according to ``docs/local-first-contract.md``.
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from meeting_memory.config.settings import load_settings
from meeting_memory.service.pipeline import Pipeline
from meeting_memory.service.recorder import RecorderService
from meeting_memory.types.meeting import MeetingMeta


def test_legacy_global_settings_require_transcription_and_backup_credentials(
    tmp_path: Path,
) -> None:
    """Characterize the global fail-fast settings model before Phase 2."""

    env_file = tmp_path / ".env"
    env_file.write_text("MEETINGS_DIR=~/Meetings\n", encoding="utf-8")

    with pytest.raises(ValidationError) as exc_info:
        load_settings(env_file)

    errors = {str(item["loc"][0]) for item in exc_info.value.errors()}
    assert errors == {
        "assemblyai_api_key",
        "b2_application_key",
        "b2_application_key_id",
        "b2_bucket_name",
        "b2_endpoint",
        "b2_region",
    }


def test_legacy_recorder_defaults_to_the_shared_system_temp_directory() -> None:
    """Characterize staging placement before Phase 2 makes it app-owned."""

    assert RecorderService().temp_dir == Path(tempfile.gettempdir())


def test_legacy_pipeline_turns_missing_remote_transcription_into_failure_markdown(
    tmp_path: Path,
) -> None:
    """Characterize the always-transcribe post-stop path before Phase 2."""

    class UnavailableTranscriber:
        audio_path: Path | None = None

        def transcribe(self, audio_path: Path):
            self.audio_path = audio_path
            raise RuntimeError("transcription is not configured")

    audio = tmp_path / "source.m4a"
    audio.write_bytes(b"durable local audio")
    meta = MeetingMeta(
        slug="2026-08-07_09-00_local-sample",
        started_at=datetime(2026, 8, 7, 9, 0, tzinfo=UTC),
        calendar_title="Local sample",
        duration_minutes=1,
    )

    transcriber = UnavailableTranscriber()
    result = Pipeline(
        meetings_dir=tmp_path / "meetings",
        transcription_client=transcriber,
    ).run(audio, meta)

    assert transcriber.audio_path == result.files.audio_path
    assert result.files.audio_path.read_bytes() == b"durable local audio"
    assert result.transcript.error is not None
    assert result.files.markdown_path.stat().st_size > 0
    assert result.transcript.assemblyai_id == "transcription-failed"
    assert "transcription is not configured" in result.files.markdown_path.read_text(
        encoding="utf-8"
    )

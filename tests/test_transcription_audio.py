"""Adversarial tests for the immutable Transcription upload boundary."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from pathlib import Path

import pytest

from meeting_memory.service.meeting_store import MeetingStore
from meeting_memory.service.transcription_audio import capture_transcription_audio
from meeting_memory.types.meeting import MeetingMeta, PostCommitPolicy


def _meeting(tmp_path: Path):
    audio = tmp_path / "source.m4a"
    audio.write_bytes(b"owned-audio")
    return MeetingStore(tmp_path / "meetings").commit(
        audio,
        MeetingMeta(
            "2026-08-10_10-00_sync",
            datetime(2026, 8, 10, 10, tzinfo=UTC),
            "Sync",
        ),
        PostCommitPolicy(transcription=True),
    )


def test_snapshot_is_read_only_and_path_swap_cannot_change_bytes(tmp_path: Path) -> None:
    files = _meeting(tmp_path)
    secret = tmp_path / "secret"
    secret.write_bytes(b"outside-secret")

    with capture_transcription_audio(files.directory.parent, files) as audio:
        files.audio_path.unlink()
        files.audio_path.symlink_to(secret)
        assert audio.read() == b"owned-audio"
        with pytest.raises(io.UnsupportedOperation):
            audio.write(b"overwrite")
        with pytest.raises(io.UnsupportedOperation):
            audio.truncate(0)

    assert secret.read_bytes() == b"outside-secret"


def test_snapshot_rejects_audio_symlink_before_capture(tmp_path: Path) -> None:
    files = _meeting(tmp_path)
    secret = tmp_path / "secret"
    secret.write_bytes(b"outside-secret")
    files.audio_path.unlink()
    files.audio_path.symlink_to(secret)

    with pytest.raises((OSError, ValueError)):
        with capture_transcription_audio(files.directory.parent, files):
            pass

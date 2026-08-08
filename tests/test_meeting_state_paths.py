"""Tests for MeetingStateStore's read-only path boundary."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from meeting_memory.service.meeting_state import MeetingStateError, MeetingStateStore
from meeting_memory.service.meeting_store import MeetingStore
from meeting_memory.types.artifacts import ArtifactFieldOwner, MeetingJob
from meeting_memory.types.capabilities import MeetingJobState
from meeting_memory.types.meeting import MeetingMeta, PostCommitPolicy


@pytest.mark.parametrize("entrypoint", ["merge", "transition", "complete"])
@pytest.mark.parametrize(
    "invalid_kind", ["outside", "nested", "symlink", "noncanonical", "mismatched-id"]
)
def test_every_state_entrypoint_rejects_invalid_path_without_mutating_target(
    tmp_path: Path,
    entrypoint: str,
    invalid_kind: str,
) -> None:
    meeting, store = _meeting(tmp_path, tmp_path / "meetings")
    invalid = _invalid_meeting(tmp_path, meeting, invalid_kind)
    transcript = invalid.resolve() / "transcript.md"
    before = transcript.read_bytes()

    with pytest.raises(MeetingStateError):
        _invoke(store, invalid, entrypoint)

    assert transcript.read_bytes() == before


def _invoke(store: MeetingStateStore, meeting: Path, entrypoint: str) -> None:
    if entrypoint == "merge":
        store.merge_fields(
            meeting, ArtifactFieldOwner.CORE, {"calendar_title": "Changed"}
        )
    elif entrypoint == "transition":
        store.transition_job(
            meeting,
            MeetingJob.TRANSCRIPTION,
            MeetingJobState.PENDING,
            MeetingJobState.RUNNING,
        )
    else:
        store.complete_backup(meeting, "0" * 64, "audio-key", "transcript-key")


def _invalid_meeting(
    tmp_path: Path,
    valid: Path,
    kind: str,
) -> Path:
    if kind == "outside":
        return _meeting(tmp_path, tmp_path / "outside")[0]
    if kind == "nested":
        nested = valid.parent / "nested" / valid.name
        nested.parent.mkdir()
        shutil.copytree(valid, nested)
        return nested
    if kind == "symlink":
        outside = _meeting(tmp_path, tmp_path / "symlink-target")[0]
        link = valid.parent / "2026-08-07_14-00_link"
        link.symlink_to(outside, target_is_directory=True)
        return link
    if kind == "noncanonical":
        noncanonical = valid.parent / "Bad_Slug"
        shutil.copytree(valid, noncanonical)
        transcript = noncanonical / "transcript.md"
        text = transcript.read_text(encoding="utf-8")
        transcript.write_text(
            text.replace(f'id: "{valid.name}"', f'id: "{noncanonical.name}"'),
            encoding="utf-8",
        )
        return noncanonical

    transcript = valid / "transcript.md"
    text = transcript.read_text(encoding="utf-8")
    transcript.write_text(text.replace(f'id: "{valid.name}"', 'id: "different"'), encoding="utf-8")
    return valid


def _meeting(
    tmp_path: Path,
    meetings_dir: Path,
) -> tuple[Path, MeetingStateStore]:
    meetings_dir.mkdir(parents=True, exist_ok=True)
    slug = f"2026-08-07_14-00_{meetings_dir.name.replace('_', '-')}"
    audio = tmp_path / f"{meetings_dir.name}.m4a"
    audio.write_bytes(b"audio")
    meeting = MeetingStore(meetings_dir).commit(
        audio,
        MeetingMeta(slug=slug, started_at=datetime(2026, 8, 7, 14, 0, tzinfo=UTC)),
        PostCommitPolicy(transcription=True, backup=True),
    ).directory
    return meeting, MeetingStateStore(meetings_dir)

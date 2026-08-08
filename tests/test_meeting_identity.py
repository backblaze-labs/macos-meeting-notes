"""Tests for immutable schema-v2 identity after local commit."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from meeting_memory.service.meeting_state import MeetingStateError, MeetingStateStore
from meeting_memory.service.meeting_store import MeetingStore
from meeting_memory.service.storage import read_frontmatter
from meeting_memory.types.artifacts import ArtifactFieldOwner
from meeting_memory.types.meeting import MeetingMeta


@pytest.mark.parametrize(
    ("field", "changed"),
    [
        ("schema_version", 3),
        ("created_by", "another-app"),
        ("id", "2026-08-07_13-00_changed"),
        ("date", "2026-08-08T13:00:00+00:00"),
    ],
)
def test_core_identity_changes_are_rejected_without_artifact_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    changed: object,
) -> None:
    meeting, store = _meeting(tmp_path)
    before = (meeting / "transcript.md").read_bytes()
    monkeypatch.setattr(
        "meeting_memory.service.meeting_state.atomic_replace_text",
        lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected write")),
    )

    with pytest.raises(MeetingStateError, match="immutable"):
        store.merge_fields(meeting, ArtifactFieldOwner.CORE, {field: changed})

    assert (meeting / "transcript.md").read_bytes() == before


def test_identical_core_identity_updates_are_noops(tmp_path: Path, monkeypatch) -> None:
    meeting, store = _meeting(tmp_path)
    frontmatter = read_frontmatter(meeting / "transcript.md")
    updates = {
        key: frontmatter[key] for key in ("schema_version", "created_by", "id", "date")
    }
    monkeypatch.setattr(
        "meeting_memory.service.meeting_state.atomic_replace_text",
        lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected write")),
    )

    result = store.merge_fields(meeting, ArtifactFieldOwner.CORE, updates)

    assert result["id"] == meeting.name


def test_mutable_core_fields_preserve_directory_identity(tmp_path: Path) -> None:
    meeting, store = _meeting(tmp_path)

    store.merge_fields(
        meeting,
        ArtifactFieldOwner.CORE,
        {"calendar_title": "Renamed", "duration_minutes": 9},
    )

    frontmatter = read_frontmatter(meeting / "transcript.md")
    assert frontmatter["calendar_title"] == "Renamed"
    assert frontmatter["duration_minutes"] == 9
    assert frontmatter["id"] == meeting.name


def _meeting(tmp_path: Path) -> tuple[Path, MeetingStateStore]:
    audio = tmp_path / "staged.m4a"
    audio.write_bytes(b"audio")
    meeting = MeetingStore(tmp_path / "meetings").commit(
        audio,
        MeetingMeta(
            slug="2026-08-07_13-00_identity",
            started_at=datetime(2026, 8, 7, 13, 0, tzinfo=UTC),
            calendar_title="Identity",
        ),
    ).directory
    return meeting, MeetingStateStore(tmp_path / "meetings")

"""Tests for conservative read-only artifact compatibility."""

from __future__ import annotations

from pathlib import Path

import pytest

from meeting_memory.service.frontmatter import dump_frontmatter
from meeting_memory.service.ownership import (
    classify_ownership,
    inspect_meeting_artifact,
    legacy_audio_paths,
    map_backup_status,
    map_speaker_status,
    map_transcription_status,
)
from meeting_memory.types.artifacts import ArtifactOwnership
from meeting_memory.types.capabilities import MeetingJobState


def test_schema_v2_ownership_requires_creator_and_supported_schema() -> None:
    assert (
        classify_ownership({"created_by": "meeting-memory", "schema_version": 2})
        is ArtifactOwnership.V2
    )
    assert (
        classify_ownership({"created_by": "another-app", "schema_version": 2})
        is ArtifactOwnership.FOREIGN
    )
    assert (
        classify_ownership({"created_by": "meeting-memory", "schema_version": 99})
        is ArtifactOwnership.FOREIGN
    )


def test_legacy_status_mapping_is_conservative() -> None:
    assert (
        map_transcription_status({"assemblyai_id": "transcription-failed"})
        is MeetingJobState.FAILED
    )
    assert map_transcription_status({"assemblyai_id": "tx-1"}) is MeetingJobState.SUCCEEDED
    assert map_backup_status({"b2_status": "upload_failed"}) is MeetingJobState.FAILED
    assert map_backup_status({"b2_status": "ok"}) is MeetingJobState.PENDING
    assert map_backup_status({}) is MeetingJobState.NOT_REQUESTED
    assert map_speaker_status({"assemblyai_id": "tx-1"}) == "needs_review"
    assert (
        map_speaker_status({"assemblyai_id": "tx-1", "speaker_aliases": {"A": "Alex"}})
        == "confirmed"
    )


def test_meeting_md_and_multipart_audio_are_read_without_writes(tmp_path: Path) -> None:
    meeting = tmp_path / "legacy"
    meeting.mkdir()
    first = meeting / "recording-part-1.m4a"
    second = meeting / "recording-part-2.m4a"
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    metadata = meeting / "meeting.md"
    metadata.write_text(_legacy_markdown(), encoding="utf-8")
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in meeting.iterdir()}

    artifact = inspect_meeting_artifact(meeting)

    assert artifact is not None
    assert artifact.ownership is ArtifactOwnership.LEGACY
    assert artifact.transcript_path.name == "meeting.md"
    assert artifact.audio_paths == (first, second)
    after = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in meeting.iterdir()}
    assert after == before


def test_transcript_with_only_generic_or_speaker_fields_is_not_claimed(tmp_path: Path) -> None:
    meeting = tmp_path / "outsider"
    meeting.mkdir()
    outsider = _legacy_markdown().replace(
        'assemblyai_id: "tx-1"\n', 'speaker_status: "confirmed"\n'
    )
    outsider = outsider.replace('b2_status: "ok"\n', 'speaker_aliases: {"A": "Alex"}\n')
    (meeting / "transcript.md").write_text(outsider, encoding="utf-8")

    assert inspect_meeting_artifact(meeting) is None


def test_generic_meeting_markdown_without_legacy_marker_is_not_claimed(tmp_path: Path) -> None:
    meeting = tmp_path / "generic"
    meeting.mkdir()
    generic = _legacy_markdown().replace('assemblyai_id: "tx-1"\n', "").replace(
        'b2_status: "ok"\n', ""
    )
    (meeting / "meeting.md").write_text(generic, encoding="utf-8")

    assert inspect_meeting_artifact(meeting) is None


def test_legacy_assembly_marker_without_b2_status_remains_owned(tmp_path: Path) -> None:
    meeting = tmp_path / "legacy-assembly"
    meeting.mkdir()
    markdown = _legacy_markdown().replace('b2_status: "ok"\n', "")
    (meeting / "transcript.md").write_text(markdown, encoding="utf-8")

    artifact = inspect_meeting_artifact(meeting)

    assert artifact is not None
    assert artifact.ownership is ArtifactOwnership.LEGACY
    assert artifact.backup_status is MeetingJobState.NOT_REQUESTED


@pytest.mark.parametrize("filename", ["meeting.md", "transcript.md"])
@pytest.mark.parametrize(
    ("markers", "owned"),
    [
        ({"assemblyai_id": None}, False),
        ({"assemblyai_id": "   "}, False),
        ({"b2_status": None}, False),
        ({"b2_status": "unknown"}, False),
        ({"assemblyai_id": "", "b2_status": "pending"}, True),
        ({"assemblyai_id": "tx-real", "b2_status": "unknown"}, True),
        ({"assemblyai_id": "transcription-failed"}, True),
    ],
)
def test_legacy_marker_values_are_validated(
    tmp_path: Path,
    filename: str,
    markers: dict[str, object],
    owned: bool,
) -> None:
    meeting = tmp_path / f"case-{filename.removesuffix('.md')}"
    meeting.mkdir()
    frontmatter = {
        "id": meeting.name,
        "date": "2026-08-07T10:00:00+00:00",
        **markers,
    }
    (meeting / filename).write_text(
        f"{dump_frontmatter(frontmatter)}\n# Transcript\n",
        encoding="utf-8",
    )

    artifact = inspect_meeting_artifact(meeting)
    assert (artifact is not None) is owned
    if markers == {"assemblyai_id": "", "b2_status": "pending"}:
        assert artifact is not None
        assert artifact.transcription_status is MeetingJobState.NOT_REQUESTED


@pytest.mark.parametrize(
    "status",
    ["ok", "succeeded", "upload_failed", "failed", "running", "pending", "uploading"],
)
def test_each_known_legacy_b2_status_is_a_marker(tmp_path: Path, status: str) -> None:
    meeting = tmp_path / status.replace("_", "-")
    meeting.mkdir()
    frontmatter = {
        "id": meeting.name,
        "date": "2026-08-07T10:00:00+00:00",
        "b2_status": status,
    }
    (meeting / "transcript.md").write_text(
        f"{dump_frontmatter(frontmatter)}\n# Transcript\n",
        encoding="utf-8",
    )

    assert inspect_meeting_artifact(meeting) is not None


def test_ownership_rejects_meeting_directory_and_metadata_symlinks(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    metadata = real / "transcript.md"
    metadata.write_text(_legacy_markdown(), encoding="utf-8")
    meeting_link = tmp_path / "meeting-link"
    meeting_link.symlink_to(real, target_is_directory=True)

    assert inspect_meeting_artifact(meeting_link) is None

    private = tmp_path / "PRIVATE"
    private.write_text(_legacy_markdown(), encoding="utf-8")
    metadata.unlink()
    metadata.symlink_to(private)
    assert inspect_meeting_artifact(real) is None
    assert private.read_text(encoding="utf-8") == _legacy_markdown()


def test_legacy_audio_paths_never_returns_symlinks(tmp_path: Path) -> None:
    meeting = tmp_path / "legacy-audio"
    meeting.mkdir()
    private = tmp_path / "PRIVATE"
    private.write_bytes(b"secret")
    (meeting / "recording.m4a").symlink_to(private)
    (meeting / "recording-part-1.m4a").symlink_to(private)
    regular = meeting / "recording-part-2.m4a"
    regular.write_bytes(b"audio")

    assert legacy_audio_paths(meeting) == (regular,)


def _legacy_markdown() -> str:
    return "\n".join(
        [
            "---",
            'id: "legacy"',
            'date: "2026-08-07T10:00:00+00:00"',
            'calendar_title: "Legacy"',
            'assemblyai_id: "tx-1"',
            'b2_status: "ok"',
            "---",
            "# Transcript",
            "",
        ]
    )

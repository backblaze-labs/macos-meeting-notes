"""Read-only ownership and legacy-state compatibility mapping."""

from __future__ import annotations

import os
import stat
from datetime import datetime
from pathlib import Path

from meeting_memory.service.frontmatter import split_frontmatter
from meeting_memory.types.artifacts import ArtifactOwnership, MeetingArtifact
from meeting_memory.types.capabilities import MeetingJobState
from meeting_memory.types.meeting import MeetingRef

SUPPORTED_SCHEMAS = {2}
LEGACY_FAILURE_SENTINEL = "transcription-failed"
VALID_SPEAKER_STATES = {"not_available", "needs_review", "confirmed"}
LEGACY_B2_STATUSES = {
    "ok",
    "succeeded",
    "upload_failed",
    "failed",
    "running",
    "pending",
    "uploading",
}


def inspect_meeting_artifact(meeting_dir: Path) -> MeetingArtifact | None:
    """Read an artifact without normalizing or writing any local file."""

    if meeting_dir.is_symlink() or not meeting_dir.is_dir():
        return None
    transcript_path = _metadata_path(meeting_dir)
    if transcript_path is None:
        return None
    try:
        frontmatter, _ = split_frontmatter(_read_regular_text(transcript_path))
    except (OSError, UnicodeError, ValueError):
        return None

    ownership = classify_ownership(frontmatter, transcript_path.name)
    if ownership is ArtifactOwnership.FOREIGN:
        return None
    slug = str(frontmatter.get("id") or meeting_dir.name)
    title = str(frontmatter.get("calendar_title") or "Untitled")
    return MeetingArtifact(
        meeting=MeetingRef(slug=slug, calendar_title=title, directory=meeting_dir),
        ownership=ownership,
        transcript_path=transcript_path,
        audio_paths=legacy_audio_paths(meeting_dir),
        transcription_status=map_transcription_status(frontmatter, ownership),
        backup_status=map_backup_status(frontmatter, ownership),
        speaker_status=map_speaker_status(frontmatter, ownership),
    )


def classify_ownership(
    frontmatter: dict[str, object],
    filename: str = "transcript.md",
) -> ArtifactOwnership:
    if (
        frontmatter.get("created_by") == "meeting-memory"
        and frontmatter.get("schema_version") in SUPPORTED_SCHEMAS
    ):
        return ArtifactOwnership.V2
    if frontmatter.get("schema_version") is not None or frontmatter.get("created_by") is not None:
        return ArtifactOwnership.FOREIGN
    if not _has_legacy_identity(frontmatter):
        return ArtifactOwnership.FOREIGN
    if filename in {"meeting.md", "transcript.md"} and _has_legacy_marker(frontmatter):
        return ArtifactOwnership.LEGACY
    return ArtifactOwnership.FOREIGN


def map_transcription_status(
    frontmatter: dict[str, object],
    ownership: ArtifactOwnership = ArtifactOwnership.LEGACY,
) -> MeetingJobState:
    if ownership is ArtifactOwnership.V2:
        return _job_state(frontmatter.get("transcription_status"))
    assemblyai_id = frontmatter.get("assemblyai_id")
    identifier = assemblyai_id.strip() if isinstance(assemblyai_id, str) else ""
    if identifier == LEGACY_FAILURE_SENTINEL:
        return MeetingJobState.FAILED
    if identifier:
        return MeetingJobState.SUCCEEDED
    return MeetingJobState.NOT_REQUESTED


def map_backup_status(
    frontmatter: dict[str, object],
    ownership: ArtifactOwnership = ArtifactOwnership.LEGACY,
) -> MeetingJobState:
    if ownership is ArtifactOwnership.V2:
        return _job_state(frontmatter.get("backup_status"))
    value = str(frontmatter.get("b2_status") or "").strip().casefold()
    mapping = {
        # Legacy success has no matching content revision, so it must be re-evaluated.
        "ok": MeetingJobState.PENDING,
        "succeeded": MeetingJobState.PENDING,
        "upload_failed": MeetingJobState.FAILED,
        "failed": MeetingJobState.FAILED,
        "running": MeetingJobState.PENDING,
        "pending": MeetingJobState.PENDING,
        "uploading": MeetingJobState.PENDING,
    }
    return mapping.get(value, MeetingJobState.NOT_REQUESTED)


def map_speaker_status(
    frontmatter: dict[str, object],
    ownership: ArtifactOwnership = ArtifactOwnership.LEGACY,
) -> str:
    value = str(frontmatter.get("speaker_status") or "")
    if value in VALID_SPEAKER_STATES:
        return value
    if ownership is ArtifactOwnership.V2:
        return "not_available"
    if frontmatter.get("speaker_aliases"):
        return "confirmed"
    if map_transcription_status(frontmatter, ownership) is MeetingJobState.SUCCEEDED:
        return "needs_review"
    return "not_available"


def legacy_audio_paths(meeting_dir: Path) -> tuple[Path, ...]:
    recording = meeting_dir / "recording.m4a"
    if not recording.is_symlink() and recording.is_file():
        return (recording,)
    return tuple(
        sorted(
            path
            for path in meeting_dir.glob("recording*.m4a")
            if not path.is_symlink() and path.is_file()
        )
    )


def _metadata_path(meeting_dir: Path) -> Path | None:
    for filename in ("transcript.md", "meeting.md"):
        path = meeting_dir / filename
        if not path.is_symlink() and path.is_file():
            return path
    return None


def _has_legacy_identity(frontmatter: dict[str, object]) -> bool:
    try:
        datetime.fromisoformat(str(frontmatter["date"]))
    except (KeyError, TypeError, ValueError):
        return False
    return bool(frontmatter.get("id"))


def _has_legacy_marker(frontmatter: dict[str, object]) -> bool:
    assemblyai_id = frontmatter.get("assemblyai_id")
    has_assembly_marker = isinstance(assemblyai_id, str) and bool(assemblyai_id.strip())
    b2_status = frontmatter.get("b2_status")
    has_b2_marker = (
        isinstance(b2_status, str) and b2_status.strip().casefold() in LEGACY_B2_STATUSES
    )
    return has_assembly_marker or has_b2_marker


def _job_state(value: object) -> MeetingJobState:
    try:
        return MeetingJobState(str(value))
    except ValueError:
        return MeetingJobState.NOT_REQUESTED


def _read_regular_text(path: Path) -> str:
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    descriptor = os.open(path, flags)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("meeting metadata is not a regular file")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        return b"".join(chunks).decode("utf-8")
    finally:
        os.close(descriptor)

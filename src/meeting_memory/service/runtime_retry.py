"""Explicit ownership-aware retry scans for schema-v2 optional jobs."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from meeting_memory.service.meeting_document import open_meeting_document
from meeting_memory.service.ownership import inspect_meeting_artifact
from meeting_memory.service.runtime_files import RuntimeMeetingHandle
from meeting_memory.service.runtime_jobs import RuntimeJobs
from meeting_memory.types.artifacts import ArtifactOwnership
from meeting_memory.types.capabilities import MeetingJobState
from meeting_memory.types.meeting import (
    MeetingDirectoryIdentity,
    MeetingFiles,
    MeetingMeta,
)

RETRYABLE = {
    MeetingJobState.PENDING,
    MeetingJobState.RUNNING,
    MeetingJobState.FAILED,
}


@dataclass(frozen=True)
class RuntimeMeeting:
    files: MeetingFiles
    transcription_status: MeetingJobState
    backup_status: MeetingJobState
    provider_job_id: str | None
    directory_identity: MeetingDirectoryIdentity

    @property
    def handle(self) -> RuntimeMeetingHandle:
        return RuntimeMeetingHandle(self.files, self.directory_identity)


def retry_v2_transcriptions(meetings_dir: Path, jobs: RuntimeJobs) -> int:
    """Retry only explicit pending/failed/stale Transcription work."""

    attempts = 0
    for meeting in _runtime_meetings(meetings_dir):
        if meeting.transcription_status in RETRYABLE:
            resume_id = (
                meeting.provider_job_id
                if meeting.transcription_status is MeetingJobState.RUNNING
                else None
            )
            jobs.retry_transcription(meeting.handle, resume_id=resume_id)
            attempts += 1
    return attempts


def retry_v2_backups(meetings_dir: Path, jobs: RuntimeJobs) -> int:
    """Explicitly process pending/failed/stale Backup work without legacy writes."""

    attempts = 0
    for meeting in _runtime_meetings(meetings_dir):
        if meeting.backup_status in RETRYABLE:
            jobs.retry_backup(meeting.handle)
            attempts += 1
    return attempts


def _runtime_meetings(meetings_dir: Path) -> tuple[RuntimeMeeting, ...]:
    if not meetings_dir.exists():
        return ()
    meetings: list[RuntimeMeeting] = []
    for meeting_dir in sorted(meetings_dir.iterdir()):
        artifact = inspect_meeting_artifact(meeting_dir)
        if artifact is None or artifact.ownership is not ArtifactOwnership.V2:
            continue
        try:
            with open_meeting_document(meetings_dir, meeting_dir) as document:
                meta = _meeting_meta(document.frontmatter)
                provider_id = _provider_id(document.frontmatter.get("assemblyai_id"))
                directory = os.fstat(document.directory_fd)
        except (KeyError, OSError, TypeError, UnicodeError, ValueError):
            continue
        meetings.append(
            RuntimeMeeting(
                MeetingFiles(
                    meta,
                    meeting_dir,
                    meeting_dir / "recording.m4a",
                    meeting_dir / "transcript.md",
                    directory_identity=MeetingDirectoryIdentity(
                        directory.st_dev,
                        directory.st_ino,
                    ),
                ),
                artifact.transcription_status,
                artifact.backup_status,
                provider_id,
                MeetingDirectoryIdentity(directory.st_dev, directory.st_ino),
            )
        )
    return tuple(meetings)


def _meeting_meta(frontmatter: dict[str, object]) -> MeetingMeta:
    speakers = frontmatter.get("speaker_candidates")
    return MeetingMeta(
        slug=str(frontmatter["id"]),
        started_at=datetime.fromisoformat(str(frontmatter["date"])),
        calendar_title=str(frontmatter["calendar_title"]),
        duration_minutes=int(frontmatter["duration_minutes"]),
        speaker_candidates=(
            tuple(str(item) for item in speakers) if isinstance(speakers, list) else ()
        ),
    )


def _provider_id(value: object) -> str | None:
    text = value.strip() if isinstance(value, str) else ""
    return text or None

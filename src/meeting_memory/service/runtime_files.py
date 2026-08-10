"""Identity checks for schema-v2 runtime job requests."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from meeting_memory.service.markdown import safe_frontmatter_text
from meeting_memory.service.meeting_document import open_meeting_document
from meeting_memory.types.meeting import MeetingDirectoryIdentity, MeetingFiles


@dataclass(frozen=True)
class RuntimeMeetingHandle:
    """Meeting paths bound to the directory validated before worker launch."""

    files: MeetingFiles
    directory_identity: MeetingDirectoryIdentity


def bind_runtime_meeting_files(
    meetings_dir: Path,
    files: MeetingFiles,
    *,
    expected_identity: MeetingDirectoryIdentity | None = None,
) -> RuntimeMeetingHandle:
    """Validate caller metadata and bind it to one pinned owned directory."""

    _validate_paths(files)
    with open_meeting_document(meetings_dir, files.directory) as document:
        expected = {
            "id": files.meta.slug,
            "date": files.meta.started_at.isoformat(),
            "duration_minutes": files.meta.duration_minutes,
            "calendar_title": safe_frontmatter_text(files.meta.calendar_title),
        }
        if any(document.frontmatter.get(key) != value for key, value in expected.items()):
            raise ValueError("runtime meeting identity does not match its files")
        info = os.fstat(document.directory_fd)
        identity = MeetingDirectoryIdentity(info.st_dev, info.st_ino)
        sealed = files.directory_identity
        if sealed is not None and expected_identity is not None and sealed != expected_identity:
            raise ValueError("runtime meeting identities disagree")
        required = sealed if sealed is not None else expected_identity
        if required is not None and identity != required:
            raise ValueError("runtime meeting directory was replaced")
    return RuntimeMeetingHandle(files, identity)


def validate_runtime_meeting_handle(
    meetings_dir: Path,
    handle: RuntimeMeetingHandle,
) -> None:
    bind_runtime_meeting_files(
        meetings_dir,
        handle.files,
        expected_identity=handle.directory_identity,
    )


def validate_runtime_meeting_files(meetings_dir: Path, files: MeetingFiles) -> None:
    """Reject caller metadata or paths that disagree with one owned document."""

    bind_runtime_meeting_files(meetings_dir, files)


def _validate_paths(files: MeetingFiles) -> None:
    if (
        files.audio_path != files.directory / "recording.m4a"
        or files.transcript_path != files.directory / "transcript.md"
    ):
        raise ValueError("runtime meeting paths are not canonical")

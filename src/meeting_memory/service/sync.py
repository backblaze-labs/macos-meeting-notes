"""Rescan local meetings and upload pending B2 artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from meeting_memory.service.storage import (
    MEETING_MARKDOWN,
    NOTES_MARKDOWN,
    RECORDING_AUDIO,
    read_frontmatter,
    update_b2_frontmatter,
)
from meeting_memory.types.meeting import B2UploadResult, MeetingFiles, MeetingMeta


class B2Client(Protocol):
    def upload_meeting(self, files: MeetingFiles) -> B2UploadResult:
        """Upload local meeting artifacts."""


@dataclass(frozen=True)
class SyncResult:
    attempted: int = 0
    uploaded: int = 0
    failed: int = 0


LEGACY_MEETING_MARKDOWN = "meeting.md"


def sync_pending_meetings(meetings_dir: Path, b2_client: B2Client) -> SyncResult:
    if not meetings_dir.exists():
        return SyncResult()

    attempted = uploaded = failed = 0
    for meeting_dir in sorted(path for path in meetings_dir.iterdir() if path.is_dir()):
        markdown_path = _sync_markdown_path(meeting_dir)
        if markdown_path is None:
            continue
        frontmatter = read_frontmatter(markdown_path)
        if not _is_sync_candidate(frontmatter):
            continue
        if frontmatter.get("b2_status") == "ok":
            continue

        attempted += 1
        files = _files_from_frontmatter(meeting_dir, markdown_path, frontmatter)
        try:
            result = b2_client.upload_meeting(files)
        except Exception:
            failed += 1
            update_b2_frontmatter(files.markdown_path, b2_status="upload_failed")
            continue

        uploaded += 1
        update_b2_frontmatter(
            files.markdown_path,
            b2_audio=result.audio_key,
            b2_transcript=result.transcript_key,
            b2_status="ok",
        )
    return SyncResult(attempted=attempted, uploaded=uploaded, failed=failed)


def _sync_markdown_path(meeting_dir: Path) -> Path | None:
    for name in (MEETING_MARKDOWN, LEGACY_MEETING_MARKDOWN):
        path = meeting_dir / name
        if path.exists():
            return path
    return None


def _is_sync_candidate(frontmatter: dict[str, object]) -> bool:
    return bool(frontmatter.get("id") and frontmatter.get("date"))


def _files_from_frontmatter(
    meeting_dir: Path,
    markdown_path: Path,
    frontmatter: dict[str, object],
) -> MeetingFiles:
    audio_paths = _recording_paths(meeting_dir)
    meta = MeetingMeta(
        slug=str(frontmatter["id"]),
        started_at=datetime.fromisoformat(str(frontmatter["date"])),
        calendar_title=str(frontmatter.get("calendar_title") or "Untitled"),
        duration_minutes=int(frontmatter.get("duration_minutes") or 0),
    )
    return MeetingFiles(
        meta=meta,
        directory=meeting_dir,
        audio_path=audio_paths[0],
        markdown_path=markdown_path,
        notes_path=meeting_dir / NOTES_MARKDOWN,
        extra_audio_paths=audio_paths[1:],
    )


def _recording_paths(meeting_dir: Path) -> tuple[Path, ...]:
    default_recording = meeting_dir / RECORDING_AUDIO
    if default_recording.exists():
        return (default_recording,)

    recording_parts = tuple(sorted(meeting_dir.glob("recording*.m4a")))
    if recording_parts:
        return recording_parts

    return (default_recording,)

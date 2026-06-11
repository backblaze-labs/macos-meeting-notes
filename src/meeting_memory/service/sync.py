"""Rescan local meetings and upload pending B2 artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from meeting_memory.service.storage import (
    MEETING_MARKDOWN,
    RECORDING_AUDIO,
    is_ours,
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


def sync_pending_meetings(meetings_dir: Path, b2_client: B2Client) -> SyncResult:
    if not meetings_dir.exists():
        return SyncResult()

    attempted = uploaded = failed = 0
    for meeting_dir in sorted(path for path in meetings_dir.iterdir() if path.is_dir()):
        if not is_ours(meeting_dir):
            continue
        frontmatter = read_frontmatter(meeting_dir / MEETING_MARKDOWN)
        if frontmatter.get("b2_status") == "ok":
            continue

        attempted += 1
        files = _files_from_frontmatter(meeting_dir, frontmatter)
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


def _files_from_frontmatter(meeting_dir: Path, frontmatter: dict[str, object]) -> MeetingFiles:
    meta = MeetingMeta(
        slug=str(frontmatter["id"]),
        started_at=datetime.fromisoformat(str(frontmatter["date"])),
        calendar_title=str(frontmatter["calendar_title"]),
        duration_minutes=int(frontmatter["duration_minutes"]),
    )
    return MeetingFiles(
        meta=meta,
        directory=meeting_dir,
        audio_path=meeting_dir / RECORDING_AUDIO,
        markdown_path=meeting_dir / MEETING_MARKDOWN,
    )

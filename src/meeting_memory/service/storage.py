"""Local meeting directory storage."""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from meeting_memory.service.frontmatter import replace_frontmatter, split_frontmatter
from meeting_memory.service.markdown import render_notes_markdown, render_transcript_markdown
from meeting_memory.types.meeting import MeetingFiles, MeetingMeta, RecentMeeting
from meeting_memory.types.summary import SummaryResult
from meeting_memory.types.transcript import TranscriptResult

TRANSCRIPT_MARKDOWN = "transcript.md"
NOTES_MARKDOWN = "notes.md"
MEETING_MARKDOWN = TRANSCRIPT_MARKDOWN
RECORDING_AUDIO = "recording.m4a"


def write_meeting_dir(
    meetings_dir: Path,
    meta: MeetingMeta,
    audio_source: Path,
    transcript: TranscriptResult,
    summary: SummaryResult,
    speaker_aliases: Mapping[str, str] | None = None,
    speaker_candidates: tuple[str, ...] = (),
) -> MeetingFiles:
    files = create_meeting_dir(meetings_dir, meta, audio_source)
    write_transcript_markdown(
        files,
        transcript,
        speaker_aliases=speaker_aliases,
        speaker_candidates=speaker_candidates,
    )
    write_notes_markdown(files, summary)
    return files


def create_meeting_dir(meetings_dir: Path, meta: MeetingMeta, audio_source: Path) -> MeetingFiles:
    meetings_dir = meetings_dir.expanduser()
    meetings_dir.mkdir(parents=True, exist_ok=True)

    slug = unique_slug(meetings_dir, meta.slug)
    final_meta = meta.with_slug(slug)
    meeting_dir = meetings_dir / slug
    meeting_dir.mkdir()

    audio_path = meeting_dir / RECORDING_AUDIO
    markdown_path = meeting_dir / TRANSCRIPT_MARKDOWN
    shutil.copy2(audio_source, audio_path)
    return MeetingFiles(
        meta=final_meta,
        directory=meeting_dir,
        audio_path=audio_path,
        markdown_path=markdown_path,
        notes_path=meeting_dir / NOTES_MARKDOWN,
    )


def write_meeting_markdown(
    files: MeetingFiles,
    transcript: TranscriptResult,
    summary: SummaryResult,
    *,
    speaker_aliases: Mapping[str, str] | None = None,
) -> None:
    write_transcript_markdown(files, transcript, speaker_aliases=speaker_aliases)
    write_notes_markdown(files, summary)


def write_transcript_markdown(
    files: MeetingFiles,
    transcript: TranscriptResult,
    *,
    speaker_aliases: Mapping[str, str] | None = None,
    speaker_candidates: tuple[str, ...] = (),
    speaker_status: str = "needs_review",
) -> None:
    files.transcript_path.write_text(
        render_transcript_markdown(
            files.meta,
            transcript,
            speaker_aliases=speaker_aliases,
            speaker_candidates=speaker_candidates,
            speaker_status=speaker_status,
        ),
        encoding="utf-8",
    )


def write_notes_markdown(files: MeetingFiles, summary: SummaryResult) -> None:
    notes_path = files.notes_path or files.directory / NOTES_MARKDOWN
    notes_path.write_text(
        render_notes_markdown(files.meta, summary),
        encoding="utf-8",
    )


def unique_slug(meetings_dir: Path, base_slug: str) -> str:
    if not (meetings_dir / base_slug).exists():
        return base_slug

    suffix = 2
    while (meetings_dir / f"{base_slug}-{suffix}").exists():
        suffix += 1
    return f"{base_slug}-{suffix}"


def read_frontmatter(markdown_path: Path) -> dict[str, object]:
    text = markdown_path.read_text(encoding="utf-8")
    frontmatter, _ = split_frontmatter(text)
    return frontmatter


def update_b2_frontmatter(
    markdown_path: Path,
    *,
    b2_audio: str | None = None,
    b2_transcript: str | None = None,
    b2_status: str,
) -> None:
    text = markdown_path.read_text(encoding="utf-8")
    frontmatter, _ = split_frontmatter(text)
    frontmatter["b2_audio"] = b2_audio
    frontmatter["b2_transcript"] = b2_transcript
    frontmatter["b2_status"] = b2_status
    markdown_path.write_text(replace_frontmatter(text, frontmatter), encoding="utf-8")


def is_ours(meeting_dir: Path) -> bool:
    markdown_path = meeting_dir / MEETING_MARKDOWN
    if not markdown_path.exists():
        return False
    try:
        frontmatter = read_frontmatter(markdown_path)
    except (OSError, ValueError):
        return False
    return bool(frontmatter.get("assemblyai_id"))


def list_recent_meetings(meetings_dir: Path, limit: int = 5) -> list[RecentMeeting]:
    if not meetings_dir.exists():
        return []

    recent: list[RecentMeeting] = []
    for meeting_dir in meetings_dir.iterdir():
        if not meeting_dir.is_dir() or not is_ours(meeting_dir):
            continue
        markdown_path = meeting_dir / MEETING_MARKDOWN
        frontmatter = read_frontmatter(markdown_path)
        recent.append(_recent_from_frontmatter(meeting_dir, markdown_path, frontmatter))

    return sorted(recent, key=lambda item: item.started_at, reverse=True)[:limit]


def _recent_from_frontmatter(
    meeting_dir: Path,
    markdown_path: Path,
    frontmatter: dict[str, object],
) -> RecentMeeting:
    return RecentMeeting(
        slug=str(frontmatter["id"]),
        calendar_title=str(frontmatter["calendar_title"]),
        started_at=datetime.fromisoformat(str(frontmatter["date"])),
        directory=meeting_dir,
        markdown_path=markdown_path,
    )

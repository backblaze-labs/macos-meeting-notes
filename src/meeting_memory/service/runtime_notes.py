"""Pinned schema-v2 Notes generation after speaker confirmation."""

from __future__ import annotations

import os
import stat
from datetime import datetime
from pathlib import Path
from typing import Protocol

from meeting_memory.service.atomic_io import atomic_replace_text_at
from meeting_memory.service.frontmatter import split_frontmatter
from meeting_memory.service.legacy_snapshot import (
    capture_legacy_document_snapshot,
    write_legacy_notes,
)
from meeting_memory.service.markdown import render_notes_markdown
from meeting_memory.service.meeting_document import open_meeting_document
from meeting_memory.service.meeting_locks import meeting_lock
from meeting_memory.service.ownership import inspect_meeting_artifact
from meeting_memory.types.artifacts import ArtifactOwnership
from meeting_memory.types.meeting import MeetingMeta
from meeting_memory.types.summary import SummaryResult


class NotesSummarizer(Protocol):
    def summarize(self, transcript_text: str) -> SummaryResult:
        raise NotImplementedError


def generate_owned_notes(
    meetings_dir: Path,
    meeting_dir: Path,
    summarizer: NotesSummarizer,
) -> Path:
    """Route an owned meeting to its schema-specific safe Notes writer."""

    artifact = inspect_meeting_artifact(meeting_dir)
    if artifact is None:
        raise ValueError("Notes require a Meeting Memory-owned artifact")
    if artifact.ownership is ArtifactOwnership.V2:
        return generate_v2_notes(meetings_dir, meeting_dir, summarizer)
    return _generate_legacy_notes(meeting_dir, summarizer)


def generate_v2_notes(
    meetings_dir: Path,
    meeting_dir: Path,
    summarizer: NotesSummarizer,
) -> Path:
    """Summarize a stable confirmed snapshot, then publish only if still current."""

    snapshot, body, meta, identity = _confirmed_snapshot(meetings_dir, meeting_dir)
    summary = summarizer.summarize(body)
    rendered = render_notes_markdown(
        meta,
        summary,
        source_transcript="transcript.md",
        speaker_status="confirmed",
    )
    with meeting_lock(meetings_dir, meeting_dir.name):
        with open_meeting_document(meetings_dir, meeting_dir) as document:
            current = os.fstat(document.directory_fd)
            if (current.st_dev, current.st_ino) != identity or document.text != snapshot:
                raise ValueError("transcript changed while Notes were being generated")
            _reject_unsafe_notes(document.directory_fd)
            atomic_replace_text_at(document.directory_fd, "notes.md", rendered)
    return meeting_dir / "notes.md"


def _generate_legacy_notes(
    meeting_dir: Path,
    summarizer: NotesSummarizer,
) -> Path:
    with capture_legacy_document_snapshot(meeting_dir) as snapshot:
        if snapshot.frontmatter.get("speaker_status") != "confirmed":
            raise ValueError("speaker aliases must be confirmed before generating notes")
        _, body = split_frontmatter(snapshot.metadata_text)
        summary = summarizer.summarize(body)
        rendered = render_notes_markdown(
            snapshot.meta,
            summary,
            source_transcript=snapshot.metadata_name,
            speaker_status="confirmed",
        )
        return write_legacy_notes(snapshot, rendered)


def _confirmed_snapshot(
    meetings_dir: Path,
    meeting_dir: Path,
) -> tuple[str, str, MeetingMeta, tuple[int, int]]:
    with open_meeting_document(meetings_dir, meeting_dir) as document:
        if document.frontmatter.get("speaker_status") != "confirmed":
            raise ValueError("speaker aliases must be confirmed before generating notes")
        _, body = split_frontmatter(document.text)
        info = os.fstat(document.directory_fd)
        return (
            document.text,
            body,
            _meta(document.frontmatter),
            (info.st_dev, info.st_ino),
        )


def _reject_unsafe_notes(directory_fd: int) -> None:
    try:
        info = os.stat("notes.md", dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("notes.md must be a regular file")


def _meta(frontmatter: dict[str, object]) -> MeetingMeta:
    return MeetingMeta(
        slug=str(frontmatter["id"]),
        started_at=datetime.fromisoformat(str(frontmatter["date"])),
        calendar_title=str(frontmatter["calendar_title"]),
        duration_minutes=int(frontmatter["duration_minutes"]),
    )

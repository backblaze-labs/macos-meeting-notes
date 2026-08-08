"""Read-only path and identity validation for schema-v2 state writes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from meeting_memory.service.frontmatter import split_frontmatter
from meeting_memory.types.meeting import validate_meeting_slug


@dataclass(frozen=True)
class ValidatedMeetingDirectory:
    path: Path
    text: str
    frontmatter: dict[str, object]


def validate_state_meeting_directory(
    meetings_dir: Path,
    meeting_dir: Path,
) -> ValidatedMeetingDirectory:
    """Require a real direct child with matching owned schema-v2 identity."""

    root = meetings_dir.expanduser().resolve(strict=True)
    candidate = meeting_dir.expanduser()
    if candidate.is_symlink():
        raise ValueError("meeting directory must not be a symlink")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_dir() or resolved.parent != root:
        raise ValueError("meeting directory must be a direct child of MEETINGS_DIR")
    validate_meeting_slug(resolved.name)

    transcript_path = resolved / "transcript.md"
    if transcript_path.is_symlink():
        raise ValueError("meeting transcript must not be a symlink")
    if transcript_path.resolve(strict=True).parent != resolved:
        raise ValueError("meeting transcript escaped its meeting directory")
    audio_path = resolved / "recording.m4a"
    if audio_path.is_symlink():
        raise ValueError("meeting audio must not be a symlink")
    if not audio_path.is_file() or audio_path.resolve(strict=True).parent != resolved:
        raise ValueError("meeting audio escaped its meeting directory")
    text = transcript_path.read_text(encoding="utf-8")
    frontmatter, _ = split_frontmatter(text)
    if (
        frontmatter.get("created_by") != "meeting-memory"
        or frontmatter.get("schema_version") != 2
    ):
        raise ValueError("state writes require an owned schema-v2 transcript")
    if frontmatter.get("id") != resolved.name:
        raise ValueError("meeting frontmatter id must match its directory name")
    return ValidatedMeetingDirectory(resolved, text, frontmatter)

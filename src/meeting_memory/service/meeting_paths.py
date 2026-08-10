"""Read-only path and identity validation for schema-v2 state writes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from meeting_memory.service.meeting_document import open_meeting_document


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

    with open_meeting_document(meetings_dir, meeting_dir) as document:
        return ValidatedMeetingDirectory(
            document.path,
            document.text,
            document.frontmatter.copy(),
        )

"""Deterministic Markdown cleanup for generated Notes profile sections."""

from __future__ import annotations

import re

from meeting_memory.types.notes_profile import (
    NotesProfileSection,
    NotesSectionAudience,
    NotesSectionFormat,
)

PERSON_HEADING_PATTERN = re.compile(
    r"^(?:[-*+]\s+)?\*\*(?P<name>[^*\n]+):\*\*(?:\s+(?P<content>.*))?$"
)
SENTENCE_BOUNDARY_PATTERN = re.compile(r"(?<=[.!?])\s+(?=[0-9A-ZÁÉÍÓÚÑ¿¡])")


def normalize_section_content(section: NotesProfileSection, content: str) -> str:
    """Apply the promised Markdown shape where it can be done without invention."""

    cleaned = content.strip()
    if not _needs_person_bullets(section):
        return cleaned
    return _normalize_person_bullets(cleaned)


def _needs_person_bullets(section: NotesProfileSection) -> bool:
    return (
        section.audience is NotesSectionAudience.EACH_PARTICIPANT
        and section.output_format is NotesSectionFormat.BULLETS
    )


def _normalize_person_bullets(content: str) -> str:
    blocks: list[str] = []
    current_name: str | None = None
    current_lines: list[str] = []

    def append_current() -> None:
        if current_name is None:
            return
        bullets = _as_bullets(current_lines)
        blocks.append(f"**{current_name}:**")
        blocks.extend(bullets or ["- _None identified._"])

    for line in content.splitlines():
        match = PERSON_HEADING_PATTERN.fullmatch(line.strip())
        if match is not None:
            append_current()
            current_name = match["name"].strip()
            current_lines = [match["content"]] if match["content"] else []
        elif current_name is not None:
            current_lines.append(line)

    append_current()
    return "\n".join(blocks) if blocks else content


def _as_bullets(lines: list[str]) -> list[str]:
    bullets: list[str] = []
    for line in lines:
        text = line.strip()
        if not text:
            continue
        if re.match(r"^[-*+]\s+", text):
            item = re.sub(r"^[-*+]\s+", "", text)
            bullets.append(f"- {item}")
        else:
            bullets.extend(f"- {sentence}" for sentence in _sentences(text))
    return bullets


def _sentences(text: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in SENTENCE_BOUNDARY_PATTERN.split(text) if part.strip())

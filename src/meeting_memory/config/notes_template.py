"""Pure parsing and validation for editable Notes instructions and layout."""

from __future__ import annotations

import re
from dataclasses import dataclass

from meeting_memory.config.defaults import (
    DEFAULT_NOTES_REPORT_TEMPLATE,
    DEFAULT_SUMMARY_PROMPT_TEMPLATE,
    NOTES_REPORT_TEMPLATE_MARKER,
)

NOTES_REPORT_PLACEHOLDERS = frozenset(
    {
        "action_items",
        "calendar_title",
        "date",
        "decisions",
        "duration_minutes",
        "meeting_id",
        "source_transcript",
        "summary",
    }
)
REQUIRED_NOTES_REPORT_PLACEHOLDERS = frozenset({"summary", "decisions", "action_items"})
PLACEHOLDER_PATTERN = re.compile(r"(?<!\{)\{([A-Za-z_][A-Za-z0-9_]*)\}(?!\})")


@dataclass(frozen=True, slots=True)
class NotesPromptDocument:
    """The provider instructions and local-only Markdown layout in one file."""

    instructions: str
    report_template: str


def parse_notes_prompt_document(text: str) -> NotesPromptDocument:
    """Parse a current document or upgrade a legacy instructions-only prompt."""

    if not isinstance(text, str) or not text.strip():
        raise ValueError("The Notes instructions and layout cannot be empty.")
    if text.count(NOTES_REPORT_TEMPLATE_MARKER) > 1:
        raise ValueError("The Notes layout marker must appear exactly once.")

    instructions, marker, report_template = text.partition(NOTES_REPORT_TEMPLATE_MARKER)
    instructions = instructions.strip()
    if not instructions:
        raise ValueError("The Notes instructions cannot be empty.")
    if not marker:
        report_template = DEFAULT_NOTES_REPORT_TEMPLATE
    report_template = report_template.strip()
    validate_notes_report_template(report_template)
    return NotesPromptDocument(instructions, report_template)


def normalize_notes_prompt_document(text: str) -> str:
    """Return the canonical combined document shown and saved by the editor."""

    document = parse_notes_prompt_document(text)
    return (
        f"{document.instructions}\n\n{NOTES_REPORT_TEMPLATE_MARKER}\n{document.report_template}\n"
    )


def default_notes_prompt_document() -> NotesPromptDocument:
    return parse_notes_prompt_document(DEFAULT_SUMMARY_PROMPT_TEMPLATE)


def validate_notes_report_template(report_template: str) -> None:
    if not report_template:
        raise ValueError("The Notes layout cannot be empty.")
    placeholders = frozenset(PLACEHOLDER_PATTERN.findall(report_template))
    unknown = placeholders - NOTES_REPORT_PLACEHOLDERS
    if unknown:
        labels = ", ".join(sorted(f"{{{name}}}" for name in unknown))
        raise ValueError(f"The Notes layout has unsupported placeholders: {labels}.")
    missing = REQUIRED_NOTES_REPORT_PLACEHOLDERS - placeholders
    if missing:
        labels = ", ".join(sorted(f"{{{name}}}" for name in missing))
        raise ValueError(f"The Notes layout is missing required placeholders: {labels}.")

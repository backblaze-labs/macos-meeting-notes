"""Pure parsing and validation for editable Notes instructions and layout."""

from __future__ import annotations

import re
from dataclasses import dataclass

from meeting_memory.config.defaults import (
    DEFAULT_NOTES_REPORT_TEMPLATE,
    DEFAULT_SUMMARY_PROMPT_TEMPLATE,
    NOTES_PROFILE_MARKER,
    NOTES_REPORT_TEMPLATE_MARKER,
)
from meeting_memory.config.notes_profiles import (
    decode_notes_profile,
    encode_notes_profile,
    render_profile_report_template,
    validate_notes_profile_ready,
)
from meeting_memory.types.notes_profile import NotesProfile

NOTES_REPORT_PLACEHOLDERS = frozenset(
    {
        "action_items",
        "calendar_title",
        "date",
        "decisions",
        "duration_minutes",
        "meeting_id",
        "source_transcript",
        "sections",
        "summary",
    }
)
REQUIRED_NOTES_REPORT_PLACEHOLDERS = frozenset({"summary", "decisions", "action_items"})
PROFILE_NOTES_REPORT_PLACEHOLDERS = frozenset({"sections"})
VISUAL_NOTES_SECTION_KEYS = ("summary", "decisions", "action_items")
PLACEHOLDER_PATTERN = re.compile(r"(?<!\{)\{([A-Za-z_][A-Za-z0-9_]*)\}(?!\})")


@dataclass(frozen=True, slots=True)
class NotesPromptDocument:
    """The provider instructions and local-only Markdown layout in one file."""

    instructions: str
    report_template: str
    profile: NotesProfile | None = None


@dataclass(frozen=True, slots=True)
class NotesVisualSection:
    """One required generated value with its user-facing Markdown heading."""

    key: str
    heading: str


@dataclass(frozen=True, slots=True)
class NotesVisualLayout:
    """The report subset supported by the native visual layout editor."""

    title: str
    sections: tuple[NotesVisualSection, ...]
    include_source: bool = True
    include_date: bool = False


def parse_notes_prompt_document(text: str) -> NotesPromptDocument:
    """Parse a current document or upgrade a legacy instructions-only prompt."""

    if not isinstance(text, str) or not text.strip():
        raise ValueError("The Notes instructions and layout cannot be empty.")
    if text.count(NOTES_REPORT_TEMPLATE_MARKER) > 1:
        raise ValueError("The Notes layout marker must appear exactly once.")
    if text.count(NOTES_PROFILE_MARKER) > 1:
        raise ValueError("The Notes profile marker must appear at most once.")

    instructions, marker, remainder = text.partition(NOTES_REPORT_TEMPLATE_MARKER)
    instructions = instructions.strip()
    if not instructions:
        raise ValueError("The Notes instructions cannot be empty.")
    if not marker:
        report_template = DEFAULT_NOTES_REPORT_TEMPLATE
        if NOTES_PROFILE_MARKER in text:
            raise ValueError("The Notes profile requires a local layout marker.")
        profile = None
    else:
        report_template, profile_marker, profile_text = remainder.partition(NOTES_PROFILE_MARKER)
        profile = decode_notes_profile(profile_text.strip()) if profile_marker else None
    report_template = report_template.strip()
    validate_notes_report_template(report_template, profile_mode=profile is not None)
    if profile is not None:
        validate_notes_profile_ready(profile)
    return NotesPromptDocument(instructions, report_template, profile)


def normalize_notes_prompt_document(text: str) -> str:
    """Return the canonical combined document shown and saved by the editor."""

    document = parse_notes_prompt_document(text)
    suffix = ""
    if document.profile is not None:
        suffix = f"\n{NOTES_PROFILE_MARKER}\n{encode_notes_profile(document.profile)}"
    return (
        f"{document.instructions}\n\n{NOTES_REPORT_TEMPLATE_MARKER}\n"
        f"{document.report_template}{suffix}\n"
    )


def compose_notes_prompt_document(
    instructions: str,
    report_template: str,
    *,
    profile: NotesProfile | None = None,
) -> str:
    """Compose the private storage format without exposing its marker to the UI."""

    suffix = ""
    if profile is not None:
        suffix = f"\n{NOTES_PROFILE_MARKER}\n{encode_notes_profile(profile)}"
    return normalize_notes_prompt_document(
        f"{instructions.rstrip()}\n\n{NOTES_REPORT_TEMPLATE_MARKER}\n"
        f"{report_template.strip()}{suffix}"
    )


def compose_notes_profile_document(instructions: str, profile: NotesProfile) -> str:
    """Compose a validated profile-backed Notes document."""

    validate_notes_profile_ready(profile)
    return compose_notes_prompt_document(
        instructions,
        render_profile_report_template(profile),
        profile=profile,
    )


def default_notes_prompt_document() -> NotesPromptDocument:
    return parse_notes_prompt_document(DEFAULT_SUMMARY_PROMPT_TEMPLATE)


def parse_visual_notes_layout(report_template: str) -> NotesVisualLayout | None:
    """Return a lossless visual model, or ``None`` for advanced Markdown."""

    validate_notes_report_template(report_template)
    lines = report_template.strip().splitlines()
    if not lines or not lines[0].startswith("# ") or lines[0].startswith("## "):
        return None
    title = lines[0][2:].strip()
    if not _valid_visual_label(title):
        return None

    include_source = False
    include_date = False
    sections: list[NotesVisualSection] = []
    index = 1
    while index < len(lines):
        line = lines[index].strip()
        index += 1
        if not line:
            continue
        if line == "**Source:** {source_transcript}":
            if include_source:
                return None
            include_source = True
            continue
        if line == "**Date:** {date}":
            if include_date:
                return None
            include_date = True
            continue
        if not line.startswith("## "):
            return None
        heading = line[3:].strip()
        while index < len(lines) and not lines[index].strip():
            index += 1
        if index >= len(lines):
            return None
        placeholder = lines[index].strip()
        index += 1
        match = re.fullmatch(r"\{([a-z_]+)\}", placeholder)
        if (
            match is None
            or match.group(1) not in VISUAL_NOTES_SECTION_KEYS
            or not _valid_visual_label(heading)
        ):
            return None
        sections.append(NotesVisualSection(match.group(1), heading))

    keys = tuple(section.key for section in sections)
    if len(set(keys)) != len(keys) or frozenset(keys) != REQUIRED_NOTES_REPORT_PLACEHOLDERS:
        return None
    return NotesVisualLayout(title, tuple(sections), include_source, include_date)


def render_visual_notes_layout(layout: NotesVisualLayout) -> str:
    """Render a visual layout model into the validated local Markdown template."""

    if not isinstance(layout, NotesVisualLayout) or not _valid_visual_label(layout.title):
        raise ValueError("The document title cannot be empty or contain Markdown fields.")
    keys = tuple(section.key for section in layout.sections)
    if len(set(keys)) != len(keys) or frozenset(keys) != REQUIRED_NOTES_REPORT_PLACEHOLDERS:
        raise ValueError("Every generated Notes section must appear exactly once.")

    blocks = [f"# {layout.title.strip()}"]
    if layout.include_date:
        blocks.append("**Date:** {date}")
    if layout.include_source:
        blocks.append("**Source:** {source_transcript}")
    for section in layout.sections:
        if not _valid_visual_label(section.heading):
            raise ValueError("Section titles cannot be empty or contain Markdown fields.")
        blocks.append(f"## {section.heading.strip()}\n\n{{{section.key}}}")
    report_template = "\n\n".join(blocks)
    validate_notes_report_template(report_template)
    return report_template


def validate_notes_report_template(report_template: str, *, profile_mode: bool = False) -> None:
    if not report_template:
        raise ValueError("The Notes layout cannot be empty.")
    placeholders = frozenset(PLACEHOLDER_PATTERN.findall(report_template))
    unknown = placeholders - NOTES_REPORT_PLACEHOLDERS
    if unknown:
        labels = ", ".join(sorted(f"{{{name}}}" for name in unknown))
        raise ValueError(f"The Notes layout has unsupported placeholders: {labels}.")
    required = (
        PROFILE_NOTES_REPORT_PLACEHOLDERS if profile_mode else REQUIRED_NOTES_REPORT_PLACEHOLDERS
    )
    missing = required - placeholders
    if missing:
        labels = ", ".join(sorted(f"{{{name}}}" for name in missing))
        raise ValueError(f"The Notes layout is missing required placeholders: {labels}.")
    if profile_mode and placeholders & REQUIRED_NOTES_REPORT_PLACEHOLDERS:
        raise ValueError("Profile layouts must use {sections} instead of legacy generated fields.")


def _valid_visual_label(value: str) -> bool:
    return bool(value.strip()) and "\n" not in value and not any(char in value for char in "{}")

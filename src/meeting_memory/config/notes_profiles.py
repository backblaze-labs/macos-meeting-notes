"""Preset, validation, and serialization helpers for Notes profiles."""

from __future__ import annotations

import json
import re
from dataclasses import replace

from meeting_memory.config.defaults import DEFAULT_NOTES_INSTRUCTIONS_TEMPLATE
from meeting_memory.types.notes_profile import (
    NotesProfile,
    NotesProfileKind,
    NotesProfileSection,
    NotesProfileVariable,
    NotesSectionAudience,
    NotesSectionFormat,
)

PROFILE_DOCUMENT_VERSION = 1
PROFILE_VARIABLE_PATTERN = re.compile(r"\{\{([a-z][a-z0-9_]*)\}\}")
MAX_PROFILE_JSON_BYTES = 65_536


def classic_notes_profile() -> NotesProfile:
    return NotesProfile(
        NotesProfileKind.CLASSIC,
        "Meeting Notes",
        (
            NotesProfileSection(
                "summary",
                "Summary",
                "Summarize the work topics, progress, risks, and next steps concisely.",
                NotesSectionFormat.PARAGRAPH,
                NotesSectionAudience.MEETING,
            ),
            NotesProfileSection(
                "decisions",
                "Decisions",
                "Include only decisions that participants explicitly made during the meeting.",
                NotesSectionFormat.BULLETS,
                NotesSectionAudience.MEETING,
            ),
            NotesProfileSection(
                "action_items",
                "Action Items",
                "List explicit tasks with an owner and due date only when stated.",
                NotesSectionFormat.CHECKLIST,
                NotesSectionAudience.MEETING,
            ),
        ),
    )


def personal_notes_profile(user_name: str = "") -> NotesProfile:
    return NotesProfile(
        NotesProfileKind.PERSONAL,
        "Personal Meeting Brief",
        (
            NotesProfileSection(
                "participant_updates",
                "Updates by person",
                (
                    "For every confirmed participant, capture what they reported: progress, "
                    "important context, blockers, and concerns. Omit people with no "
                    "substantive update."
                ),
                NotesSectionFormat.BULLETS,
                NotesSectionAudience.EACH_PARTICIPANT,
            ),
            NotesProfileSection(
                "my_tasks",
                "My tasks",
                (
                    "Include only tasks explicitly assigned to {{user_name}}. Do not include tasks "
                    "owned by other participants or infer ownership from general discussion."
                ),
                NotesSectionFormat.CHECKLIST,
                NotesSectionAudience.ME,
            ),
        ),
        (NotesProfileVariable("user_name", "Your name", user_name.strip(), required=True),),
    )


def custom_notes_profile() -> NotesProfile:
    base = personal_notes_profile()
    return replace(base, kind=NotesProfileKind.CUSTOM)


def default_profile_instructions() -> str:
    return DEFAULT_NOTES_INSTRUCTIONS_TEMPLATE.strip()


def validate_notes_profile_ready(profile: NotesProfile) -> None:
    missing = tuple(
        variable.label
        for variable in profile.variables
        if variable.required and not variable.value.strip()
    )
    if missing:
        raise ValueError(f"Complete the required template field: {', '.join(missing)}.")
    known = {variable.key for variable in profile.variables}
    used = {
        key
        for section in profile.sections
        for key in PROFILE_VARIABLE_PATTERN.findall(section.instructions)
    }
    unknown = used - known
    if unknown:
        labels = ", ".join(sorted(f"{{{{{key}}}}}" for key in unknown))
        raise ValueError(f"Section guidance uses unknown template fields: {labels}.")
    if any(section.audience is NotesSectionAudience.ME for section in profile.sections):
        identity = profile.variable_for("user_name")
        if identity is None or not identity.value.strip():
            raise ValueError("Complete the required template field: Your name.")


def render_profile_report_template(profile: NotesProfile) -> str:
    blocks = [f"# {profile.report_title.strip()}"]
    if profile.include_date:
        blocks.append("**Date:** {date}")
    if profile.include_source:
        blocks.append("**Source:** {source_transcript}")
    blocks.append("{sections}")
    return "\n\n".join(blocks)


def rendered_section_guidance(profile: NotesProfile, section: NotesProfileSection) -> str:
    validate_notes_profile_ready(profile)
    values = {variable.key: variable.value.strip() for variable in profile.variables}
    guidance = PROFILE_VARIABLE_PATTERN.sub(
        lambda match: values[match.group(1)], section.instructions
    )
    audience = {
        NotesSectionAudience.MEETING: "Cover the meeting as a whole.",
        NotesSectionAudience.EACH_PARTICIPANT: (
            "Group the result by confirmed speaker name and keep each person's "
            "contribution distinct."
        ),
        NotesSectionAudience.ME: (
            f"Include only content that applies to {values['user_name']}; exclude other owners."
        ),
    }[section.audience]
    output = {
        NotesSectionFormat.PARAGRAPH: "Return one concise Markdown paragraph.",
        NotesSectionFormat.BULLETS: "Return a concise Markdown bullet list.",
        NotesSectionFormat.CHECKLIST: "Return GitHub-Flavored Markdown checklist items.",
    }[section.output_format]
    return f"{audience} {output} {guidance.strip()} If none exists, return _None identified._"


def encode_notes_profile(profile: NotesProfile) -> str:
    payload = {
        "version": PROFILE_DOCUMENT_VERSION,
        "kind": profile.kind.value,
        "report_title": profile.report_title,
        "include_source": profile.include_source,
        "include_date": profile.include_date,
        "variables": [
            {
                "key": variable.key,
                "label": variable.label,
                "value": variable.value,
                "required": variable.required,
            }
            for variable in profile.variables
        ],
        "sections": [
            {
                "key": section.key,
                "title": section.title,
                "instructions": section.instructions,
                "output_format": section.output_format.value,
                "audience": section.audience.value,
            }
            for section in profile.sections
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    if len(encoded.encode()) > MAX_PROFILE_JSON_BYTES:
        raise ValueError("Notes profile is too large to save safely.")
    return encoded


def decode_notes_profile(text: str) -> NotesProfile:
    if not isinstance(text, str) or len(text.encode()) > MAX_PROFILE_JSON_BYTES:
        raise ValueError("Notes profile is not bounded text.")
    try:
        payload = json.loads(text)
        _require_keys(
            payload,
            {
                "version",
                "kind",
                "report_title",
                "include_source",
                "include_date",
                "variables",
                "sections",
            },
        )
        if payload["version"] != PROFILE_DOCUMENT_VERSION:
            raise ValueError("unsupported Notes profile version")
        variables = tuple(_decode_variable(item) for item in payload["variables"])
        sections = tuple(_decode_section(item) for item in payload["sections"])
        return NotesProfile(
            NotesProfileKind(payload["kind"]),
            str(payload["report_title"]),
            sections,
            variables,
            payload["include_source"],
            payload["include_date"],
        )
    except Exception:
        raise ValueError("The saved Notes profile is invalid or unsupported.") from None


def _decode_variable(payload: object) -> NotesProfileVariable:
    _require_keys(payload, {"key", "label", "value", "required"})
    assert isinstance(payload, dict)
    return NotesProfileVariable(
        str(payload["key"]), str(payload["label"]), str(payload["value"]), payload["required"]
    )


def _decode_section(payload: object) -> NotesProfileSection:
    _require_keys(payload, {"key", "title", "instructions", "output_format", "audience"})
    assert isinstance(payload, dict)
    return NotesProfileSection(
        str(payload["key"]),
        str(payload["title"]),
        str(payload["instructions"]),
        NotesSectionFormat(payload["output_format"]),
        NotesSectionAudience(payload["audience"]),
    )


def _require_keys(payload: object, expected: set[str]) -> None:
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ValueError("invalid Notes profile object")

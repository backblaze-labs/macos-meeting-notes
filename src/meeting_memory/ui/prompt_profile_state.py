"""Pure state helpers shared by the native Notes profile controller."""

from __future__ import annotations

from dataclasses import replace

from meeting_memory.config.defaults import DEFAULT_NOTES_REPORT_TEMPLATE
from meeting_memory.config.notes_profiles import classic_notes_profile
from meeting_memory.config.notes_template import NotesPromptDocument, parse_visual_notes_layout
from meeting_memory.types.notes_profile import (
    NotesProfile,
    NotesProfileKind,
    NotesProfileVariable,
    NotesSectionAudience,
)


def profile_from_document(document: NotesPromptDocument) -> NotesProfile:
    """Load a current profile or losslessly import the visual legacy subset."""

    if document.profile is not None:
        return document.profile
    base = classic_notes_profile()
    layout = parse_visual_notes_layout(document.report_template)
    if layout is None:
        return replace(base, kind=NotesProfileKind.CUSTOM)
    by_key = {section.key: section for section in base.sections}
    sections = tuple(
        replace(by_key[section.key], title=section.heading) for section in layout.sections
    )
    kind = (
        NotesProfileKind.CLASSIC
        if document.report_template.strip() == DEFAULT_NOTES_REPORT_TEMPLATE.strip()
        else NotesProfileKind.CUSTOM
    )
    return NotesProfile(
        kind,
        layout.title,
        sections,
        include_source=layout.include_source,
        include_date=layout.include_date,
    )


def user_name_for(profile: NotesProfile) -> str:
    variable = profile.variable_for("user_name")
    return "" if variable is None else variable.value


def with_user_name(profile: NotesProfile, value: str) -> NotesProfile:
    variables = list(profile.variables)
    required = any(section.audience is NotesSectionAudience.ME for section in profile.sections)
    replacement = NotesProfileVariable("user_name", "Your name", value.strip(), required=required)
    for index, variable in enumerate(variables):
        if variable.key == "user_name":
            variables[index] = replacement
            break
    else:
        if value.strip() or required:
            variables.append(replacement)
    return replace(profile, variables=tuple(variables))


def custom_profile(profile: NotesProfile) -> NotesProfile:
    return replace(profile, kind=NotesProfileKind.CUSTOM)


def next_section_key(profile: NotesProfile) -> str:
    used = {section.key for section in profile.sections}
    index = 1
    while f"section_{index}" in used:
        index += 1
    return f"section_{index}"

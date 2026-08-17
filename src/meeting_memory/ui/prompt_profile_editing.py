"""Pure edit operations for the native Notes profile workspace."""

from __future__ import annotations

from dataclasses import replace

from meeting_memory.config.notes_profiles import classic_notes_profile, personal_notes_profile
from meeting_memory.types.notes_profile import (
    NotesProfile,
    NotesProfileKind,
    NotesProfileSection,
    NotesSectionAudience,
    NotesSectionFormat,
)
from meeting_memory.ui.prompt_profile_state import custom_profile, next_section_key, with_user_name


def select_template(kind: NotesProfileKind, *, user_name: str = "") -> NotesProfile:
    if kind is NotesProfileKind.CLASSIC:
        return classic_notes_profile()
    if kind is NotesProfileKind.PERSONAL:
        return personal_notes_profile(user_name)
    raise ValueError("Only built-in templates can be selected directly.")


def replace_section(
    profile: NotesProfile,
    index: int,
    *,
    title: str,
    instructions: str,
    output_format: NotesSectionFormat,
    audience: NotesSectionAudience,
) -> NotesProfile:
    replacement = replace(
        profile.sections[index],
        title=title,
        instructions=instructions,
        output_format=output_format,
        audience=audience,
    )
    if replacement == profile.sections[index]:
        return profile
    sections = list(profile.sections)
    sections[index] = replacement
    updated = replace(profile, sections=tuple(sections))
    updated = with_user_name(updated, _user_name(profile))
    return custom_profile(updated)


def add_section(profile: NotesProfile) -> tuple[NotesProfile, int]:
    section = NotesProfileSection(
        next_section_key(profile),
        "New section",
        "Describe the specific meeting information this section should capture.",
        NotesSectionFormat.BULLETS,
        NotesSectionAudience.MEETING,
    )
    updated = custom_profile(replace(profile, sections=(*profile.sections, section)))
    return updated, len(updated.sections) - 1


def remove_section(profile: NotesProfile, index: int) -> tuple[NotesProfile, int]:
    if len(profile.sections) == 1:
        return profile, 0
    sections = tuple(
        section for position, section in enumerate(profile.sections) if position != index
    )
    updated = custom_profile(replace(profile, sections=sections))
    return updated, min(index, len(sections) - 1)


def move_section(profile: NotesProfile, index: int, shift: int) -> tuple[NotesProfile, int]:
    destination = index + shift
    if destination < 0 or destination >= len(profile.sections):
        return profile, index
    sections = list(profile.sections)
    sections[index], sections[destination] = sections[destination], sections[index]
    return custom_profile(replace(profile, sections=tuple(sections))), destination


def _user_name(profile: NotesProfile) -> str:
    variable = profile.variable_for("user_name")
    return "" if variable is None else variable.value

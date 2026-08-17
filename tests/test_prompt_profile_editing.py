"""Pure behavior tests for the Notes profile workspace."""

from dataclasses import replace

from meeting_memory.config.defaults import DEFAULT_NOTES_REPORT_TEMPLATE
from meeting_memory.config.notes_profiles import personal_notes_profile
from meeting_memory.config.notes_template import NotesPromptDocument
from meeting_memory.types.notes_profile import (
    NotesProfileKind,
    NotesSectionAudience,
    NotesSectionFormat,
)
from meeting_memory.ui.prompt_profile_editing import (
    add_section,
    move_section,
    remove_section,
    replace_section,
)
from meeting_memory.ui.prompt_profile_state import profile_from_document, with_user_name


def test_default_document_opens_as_the_classic_template() -> None:
    profile = profile_from_document(
        NotesPromptDocument("Keep it concise.", DEFAULT_NOTES_REPORT_TEMPLATE)
    )

    assert profile.kind is NotesProfileKind.CLASSIC
    assert tuple(section.key for section in profile.sections) == (
        "summary",
        "decisions",
        "action_items",
    )


def test_advanced_section_editing_turns_a_preset_into_custom() -> None:
    profile = personal_notes_profile("Eduardo")

    updated = replace_section(
        profile,
        0,
        title="Team pulse",
        instructions="Capture progress and blockers for each person.",
        output_format=NotesSectionFormat.BULLETS,
        audience=NotesSectionAudience.EACH_PARTICIPANT,
    )

    assert updated.kind is NotesProfileKind.CUSTOM
    assert updated.sections[0].title == "Team pulse"
    assert updated.variable_for("user_name").value == "Eduardo"


def test_section_add_remove_and_order_preserve_a_valid_profile() -> None:
    profile, selected = add_section(personal_notes_profile("Eduardo"))
    assert selected == 2
    assert len(profile.sections) == 3

    profile, selected = move_section(profile, selected, -1)
    assert selected == 1
    assert profile.sections[1].key == "section_1"

    profile, selected = remove_section(profile, selected)
    assert selected == 1
    assert tuple(section.key for section in profile.sections) == (
        "participant_updates",
        "my_tasks",
    )


def test_only_me_section_makes_user_name_required() -> None:
    profile = replace(personal_notes_profile("Eduardo"), variables=())
    profile = with_user_name(profile, "Eduardo")

    assert profile.variable_for("user_name").required is True

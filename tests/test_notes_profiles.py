"""Tests for versioned Notes generation profiles."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import pytest

from meeting_memory.config.notes_profiles import (
    classic_notes_profile,
    decode_notes_profile,
    encode_notes_profile,
    personal_notes_profile,
    render_profile_report_template,
    rendered_section_guidance,
    validate_notes_profile_ready,
)
from meeting_memory.config.notes_template import (
    compose_notes_profile_document,
    parse_notes_prompt_document,
)
from meeting_memory.repo.summarizer import profile_result_from_json
from meeting_memory.service.markdown import render_notes_markdown
from meeting_memory.types.meeting import MeetingMeta
from meeting_memory.types.notes_profile import NotesProfileVariable
from meeting_memory.types.summary import GeneratedNotesSection, SummaryResult


def test_classic_profile_round_trips_through_private_prompt_document() -> None:
    profile = classic_notes_profile()

    text = compose_notes_profile_document("Keep it concise.", profile)
    document = parse_notes_prompt_document(text)

    assert document.instructions == "Keep it concise."
    assert document.profile == profile
    assert document.report_template == render_profile_report_template(profile)
    assert decode_notes_profile(encode_notes_profile(profile)) == profile


def test_personal_profile_requires_the_users_name() -> None:
    with pytest.raises(ValueError, match="Your name"):
        validate_notes_profile_ready(personal_notes_profile())

    profile = personal_notes_profile("Eduardo")

    validate_notes_profile_ready(profile)
    guidance = rendered_section_guidance(profile, profile.sections[1])
    assert "Eduardo" in guidance
    assert "{{user_name}}" not in guidance
    assert "exclude other owners" in guidance


def test_profile_rejects_unknown_template_variables() -> None:
    profile = personal_notes_profile("Eduardo")
    profile = replace(
        profile,
        variables=(NotesProfileVariable("another_name", "Another name", "Alex"),),
    )

    with pytest.raises(ValueError, match="unknown template fields"):
        validate_notes_profile_ready(profile)


def test_profile_notes_render_only_configured_sections() -> None:
    profile = personal_notes_profile("Eduardo")
    result = SummaryResult(
        summary=None,
        sections=(
            GeneratedNotesSection(
                "participant_updates",
                "Updates by person",
                "- **Alex:** Shipped the migration.",
            ),
            GeneratedNotesSection("my_tasks", "My tasks", "- [ ] Review the launch checklist."),
        ),
    )

    rendered = render_notes_markdown(
        MeetingMeta("meeting", datetime(2026, 8, 17, 10, 0), "Team sync", 30),
        result,
        report_template=render_profile_report_template(profile),
    )

    assert "## Updates by person" in rendered
    assert "## My tasks" in rendered
    assert "## Decisions" not in rendered
    assert "## Action Items" not in rendered


def test_profile_codec_rejects_unrecognized_shape() -> None:
    with pytest.raises(ValueError, match="invalid or unsupported"):
        decode_notes_profile('{"version":1}')


def test_profile_parser_rejects_sections_outside_the_trusted_recipe() -> None:
    profile = personal_notes_profile("Eduardo")
    response = (
        '{"sections":['
        '{"id":"my_tasks","content":"- [ ] Review the launch plan."},'
        '{"id":"participant_updates","content":"- **Alex:** Shipped the fix."}'
        "]}"
    )

    with pytest.raises(ValueError, match="IDs do not match"):
        profile_result_from_json(response, profile)


def test_profile_parser_rejects_blank_generated_content() -> None:
    profile = personal_notes_profile("Eduardo")
    response = (
        '{"sections":['
        '{"id":"participant_updates","content":"- **Alex:** Shipped the fix."},'
        '{"id":"my_tasks","content":"   "}'
        "]}"
    )

    with pytest.raises(ValueError, match="must not be blank"):
        profile_result_from_json(response, profile)

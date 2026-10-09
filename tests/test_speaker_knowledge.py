"""Local known-person KB compatibility and bounded whole-turn excerpts."""

from types import SimpleNamespace

import pytest

from meeting_memory.config.settings import Settings
from meeting_memory.service.speaker_excerpt import MAX_SPEAKER_EXCERPT_CHARS, speaker_excerpt
from meeting_memory.service.speaker_suggestions_composition import speaker_review_loader
from meeting_memory.types.speakers import KnownSpeaker
from meeting_memory.ui.configuration_forms import _known_speakers_value
from meeting_memory.ui.preference_forms import speakers_from_form_rows
from meeting_memory.ui.preferences import (
    known_speakers_env_value,
    parse_known_speakers_text,
    render_known_speakers,
)


@pytest.mark.parametrize(
    "raw",
    [
        '[{"name":"Alex","matches":["alex@example.com"],"description":"Launch planning"}]',
        '{"Alex":{"matches":["alex@example.com"],"description":"Launch planning"}}',
    ],
)
def test_rich_known_person_configuration_preserves_description(raw):
    assert Settings.parse_known_speakers(raw) == (
        KnownSpeaker("Alex", ("alex@example.com",), "Launch planning"),
    )


def test_description_survives_native_and_fallback_serialization():
    people = (KnownSpeaker("Alex", ("alex@example.com",), "Launch planning"),)
    for text in (
        _known_speakers_value(people),
        known_speakers_env_value(people),
        render_known_speakers(people),
    ):
        assert Settings.parse_known_speakers(text) == people
    assert parse_known_speakers_text(render_known_speakers(people)) == people
    assert speakers_from_form_rows([("Alex", "alex@example.com", "Launch planning")]) == people


def test_description_is_optional_and_bounded():
    assert Settings.parse_known_speakers('{"Alex":["alex"]}') == (KnownSpeaker("Alex", ("alex",)),)
    with pytest.raises(ValueError):
        KnownSpeaker("Alex", (), "x" * 301)


def test_excerpt_omits_metadata_and_stops_at_whole_turn():
    body = "**A** (0:00:01): I am Alex.\n**B** (0:00:02): " + "x" * MAX_SPEAKER_EXCERPT_CHARS
    turns = speaker_excerpt(body)
    assert len(turns) == 1 and turns[0].text == "I am Alex."


def test_composition_uses_only_existing_notes_key_and_gate():
    config = SimpleNamespace(
        notes=SimpleNamespace(api_key="notes-key"),
        settings=SimpleNamespace(known_speakers=(KnownSpeaker("Alex"),)),
    )
    loader = speaker_review_loader(config, enabled=lambda: False)
    assert loader._client._api_key == "notes-key"
    assert not loader._enabled() and not loader._client._admit_request()
    assert speaker_review_loader(SimpleNamespace(notes=None)) is None

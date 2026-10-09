"""Grounded speaker proposals, manual fallback, and stale-state protection."""

from dataclasses import replace
from unittest.mock import Mock

import pytest

from meeting_memory.service.speaker_suggestions import SpeakerSuggestionLoader, validate_suggestions
from meeting_memory.types.speakers import (
    KnownSpeaker,
    SpeakerIdentificationRequest,
    SpeakerIdentificationResult,
    SpeakerSuggestion,
    SpeakerUtterance,
)
from meeting_memory.types.transcript import SpeakerReviewState


def result(*pairs):
    return SpeakerIdentificationResult(tuple(SpeakerSuggestion(*pair) for pair in pairs))


def people(*names):
    return tuple(KnownSpeaker(name, (), "Project context") for name in names)


@pytest.fixture
def state(tmp_path):
    return SpeakerReviewState(
        tmp_path,
        tmp_path / "transcript.md",
        ("A", "B"),
        ("Alex", "Casey", "Drew"),
        {},
        "needs_review",
        {},
        "tx-123",
        speaker_utterances=(
            SpeakerUtterance("A", "I am Alex and own the launch plan."),
            SpeakerUtterance("B", "I am Casey and update the slides."),
        ),
    )


def load_fixture(monkeypatch, state):
    current = [state]
    monkeypatch.setattr(
        "meeting_memory.service.speaker_suggestions.load_speaker_review", lambda _p: current[0]
    )
    return current


def test_proposals_are_read_only_and_cached(monkeypatch, state):
    load_fixture(monkeypatch, state)
    state.transcript_path.write_text("unchanged")
    client = Mock()
    client.identify.return_value = result(("A", "Alex", "I am Alex and own the launch plan."))
    loader = SpeakerSuggestionLoader(client, people(*state.speaker_candidates))
    assert loader(state.meeting_directory).speaker_suggestions == {"A": "Alex"}
    assert loader(state.meeting_directory).speaker_suggestions == {"A": "Alex"}
    assert state.transcript_path.read_text() == "unchanged" and state.speaker_aliases == {}
    assert not (state.meeting_directory / "notes.md").exists()
    client.identify.assert_called_once()
    assert not hasattr(client.identify.call_args.args[0], "assemblyai_id")


@pytest.mark.parametrize(
    "change, roster",
    [
        ({"speaker_candidates": ("External",)}, people("Alex")),
        ({"speaker_candidates": ()}, people("Alex")),
        ({}, ()),
        ({"speaker_utterances": ()}, people("Alex", "Casey", "Drew")),
        (
            {"speaker_status": "confirmed", "speaker_aliases": {"A": "Alex"}},
            people("Alex", "Casey", "Drew"),
        ),
    ],
)
def test_manual_fallback_makes_no_provider_request(monkeypatch, state, change, roster):
    current = replace(state, **change)
    load_fixture(monkeypatch, current)
    client = Mock()
    loaded = SpeakerSuggestionLoader(client, roster)(state.meeting_directory)
    assert loaded.speaker_suggestions == {} and loaded.speaker_aliases == current.speaker_aliases
    client.identify.assert_not_called()


def test_api_failure_message_is_safe(monkeypatch, state):
    load_fixture(monkeypatch, state)
    client = Mock()
    client.identify.side_effect = RuntimeError("SECRET PRIVATE TEXT")
    loaded = SpeakerSuggestionLoader(client, people(*state.speaker_candidates))(
        state.meeting_directory
    )
    assert loaded.speaker_suggestions == {} and "SECRET" not in loaded.suggestion_message


def test_notes_pause_prevents_requests_and_cached_display(monkeypatch, state):
    load_fixture(monkeypatch, state)
    client = Mock()
    client.identify.return_value = result(("A", "Alex", "I am Alex and own the launch plan."))
    enabled = [False]
    loader = SpeakerSuggestionLoader(
        client, people(*state.speaker_candidates), enabled=lambda: enabled[0]
    )
    assert not loader(state.meeting_directory).speaker_suggestions
    client.identify.assert_not_called()
    enabled[0] = True
    assert loader(state.meeting_directory).speaker_suggestions
    enabled[0] = False
    assert not loader(state.meeting_directory).speaker_suggestions
    client.identify.assert_called_once()


@pytest.mark.parametrize(
    "pairs",
    [
        (("X", "Alex", "I am Alex and own the launch plan."),),
        (("A", "Invented", "I am Alex and own the launch plan."),),
        (("A", "Alex", "Fabricated unrelated evidence."),),
        (("A", "Alex", "I am Casey and update the slides."),),
        (("A", "Alex", ""),),
        (
            ("A", "Alex", "I am Alex and own the launch plan."),
            ("A", "Casey", "I am Alex and own the launch plan."),
        ),
        (
            ("A", "Alex", "I am Alex and own the launch plan."),
            ("B", "Alex", "I am Casey and update the slides."),
        ),
    ],
)
def test_invalid_or_ambiguous_mapping_is_rejected(state, pairs):
    request = SpeakerIdentificationRequest(state.speaker_utterances, people("Alex", "Casey"))
    assert validate_suggestions(result(*pairs), request) == ()


def test_partial_evidenced_mapping_does_not_force_attendees_to_speak(state):
    request = SpeakerIdentificationRequest(
        state.speaker_utterances, people(*state.speaker_candidates)
    )
    proposal = result(("A", "Alex", "I am Alex and own the launch plan."))
    assert validate_suggestions(proposal, request) == proposal.suggestions


def test_changed_transcript_during_request_drops_proposals(monkeypatch, state):
    current = load_fixture(monkeypatch, state)
    client = Mock()

    def identify(_request):
        current[0] = replace(state, speaker_utterances=(SpeakerUtterance("A", "Edited text"),))
        return result(("A", "Alex", "I am Alex and own the launch plan."))

    client.identify.side_effect = identify
    loaded = SpeakerSuggestionLoader(client, people(*state.speaker_candidates))(
        state.meeting_directory
    )
    assert loaded is not state and not loaded.speaker_suggestions
    assert "changed" in loaded.suggestion_message


@pytest.mark.parametrize(
    "change",
    [
        {"assemblyai_id": "new-id"},
        {"speaker_utterances": (SpeakerUtterance("A", "I am Alex again today."),)},
        {"speaker_candidates": ("Alex", "Casey")},
        {"speaker_labels": ("A",)},
    ],
)
def test_transcript_changes_invalidate_cache(monkeypatch, state, change):
    current = load_fixture(monkeypatch, state)
    client = Mock()
    client.identify.return_value = result(("A", "Alex", "I am Alex and own the launch plan."))
    loader = SpeakerSuggestionLoader(client, people(*state.speaker_candidates))
    loader(state.meeting_directory)
    current[0] = replace(state, **change)
    loader(state.meeting_directory)
    assert client.identify.call_count == 2

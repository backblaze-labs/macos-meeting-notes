"""Partially known attendee lists and explicitly marked elimination proposals."""

from dataclasses import replace
from unittest.mock import Mock

import pytest
from test_speaker_suggestions import load_fixture, people, result
from test_speaker_suggestions import state as state

from meeting_memory.service.speaker_suggestions import SpeakerSuggestionLoader, validate_suggestions
from meeting_memory.types.speakers import (
    KnownSpeaker,
    SpeakerIdentificationRequest,
    SpeakerIdentificationResult,
    SpeakerSuggestion,
    SpeakerUtterance,
)


@pytest.mark.parametrize("roster", [people("Alex"), ()])
def test_named_attendees_without_profiles_do_not_block_request(monkeypatch, state, roster):
    load_fixture(monkeypatch, state)
    client = Mock()
    client.identify.return_value = result(("A", "Alex", "I am Alex and own the launch plan."))
    loaded = SpeakerSuggestionLoader(client, roster)(state.meeting_directory)
    assert loaded.speaker_suggestions == {"A": "Alex"}
    request = client.identify.call_args.args[0]
    assert tuple(p.name for p in request.people) == state.speaker_candidates
    assert request.people[1].description == ""
    assert request.allow_elimination


def test_email_only_attendee_is_local_and_blocks_only_elimination(monkeypatch, state):
    state = replace(state, speaker_candidates=("Alex", "Casey", "external@example.com"))
    load_fixture(monkeypatch, state)
    client = Mock()
    client.identify.return_value = result(("A", "Alex", "I am Alex and own the launch plan."))
    loaded = SpeakerSuggestionLoader(client, people("Alex"))(state.meeting_directory)
    assert loaded.speaker_suggestions == {"A": "Alex"}
    request = client.identify.call_args.args[0]
    assert tuple(p.name for p in request.people) == ("Alex", "Casey")
    assert "@" not in repr(request) and not request.allow_elimination
    assert loaded.speaker_candidates == state.speaker_candidates


def test_historical_email_candidate_uses_exact_local_roster_alias(monkeypatch, state):
    state = replace(state, speaker_candidates=("Alex", "casey@example.com"))
    load_fixture(monkeypatch, state)
    client = Mock()
    client.identify.return_value = result(("B", "Casey", "I am Casey and update the slides."))
    roster = (*people("Alex"), KnownSpeaker("Casey", ("CASEY@example.com",)))
    loaded = SpeakerSuggestionLoader(client, roster)(state.meeting_directory)
    assert loaded.speaker_suggestions == {"B": "Casey"}
    assert tuple(p.name for p in client.identify.call_args.args[0].people) == ("Alex", "Casey")
    assert client.identify.call_args.args[0].allow_elimination
    assert loaded.speaker_candidates == state.speaker_candidates  # Keep local review identity.


def test_ambiguous_local_alias_does_not_guess_between_profiles(monkeypatch, state):
    state = replace(state, speaker_candidates=("Alex", "shared@example.com"))
    load_fixture(monkeypatch, state)
    client = Mock()
    client.identify.return_value = result()
    roster = (
        *people("Alex"),
        KnownSpeaker("Casey", ("shared@example.com",)),
        KnownSpeaker("Drew", ("shared@example.com",)),
    )
    SpeakerSuggestionLoader(client, roster)(state.meeting_directory)
    request = client.identify.call_args.args[0]
    assert tuple(p.name for p in request.people) == ("Alex",)
    assert not request.allow_elimination


def elimination_request():
    return SpeakerIdentificationRequest(
        (SpeakerUtterance("A", "I am Alex."), SpeakerUtterance("B", "The launch is ready.")),
        people("Alex", "Casey"),
    )


def elimination_result():
    return SpeakerIdentificationResult(
        (
            SpeakerSuggestion("A", "Alex", "I am Alex."),
            SpeakerSuggestion("B", "Casey", "The launch is ready.", "elimination"),
        )
    )


def test_single_remaining_attendee_can_be_proposed_by_elimination():
    proposal = elimination_result()
    assert validate_suggestions(proposal, elimination_request()) == proposal.suggestions


@pytest.mark.parametrize(
    "change",
    [
        {"allow_elimination": False},
        {"people": people("Alex", "Casey", "Drew")},  # Another attendee may be silent.
        {"utterances": (*elimination_request().utterances, SpeakerUtterance("C", "Other."))},
    ],
)
def test_elimination_abstains_when_remaining_identity_is_not_unique(change):
    proposal = elimination_result()
    assert validate_suggestions(proposal, replace(elimination_request(), **change)) == (
        proposal.suggestions[0],
    )


def test_unknown_fragments_do_not_force_an_extra_person():
    request = elimination_request()
    request = replace(request, utterances=(*request.utterances, SpeakerUtterance("Unknown", "um")))
    proposal = elimination_result()
    assert validate_suggestions(proposal, request) == proposal.suggestions
    unknown = replace(proposal.suggestions[1], label="Unknown", evidence="um")
    assert validate_suggestions(
        SpeakerIdentificationResult((proposal.suggestions[0], unknown)), request
    ) == (proposal.suggestions[0],)


def test_elimination_without_direct_matches_is_not_a_supported_identity_guess():
    request = SpeakerIdentificationRequest((SpeakerUtterance("A", "Hello."),), people("Alex"))
    proposal = SpeakerIdentificationResult(
        (SpeakerSuggestion("A", "Alex", "Hello.", "elimination"),)
    )
    assert validate_suggestions(proposal, request) == ()


def test_elimination_still_requires_real_same_label_quote():
    proposal = elimination_result()
    fabricated = replace(proposal.suggestions[1], evidence="I never said that.")
    assert validate_suggestions(
        SpeakerIdentificationResult((proposal.suggestions[0], fabricated)), elimination_request()
    ) == (proposal.suggestions[0],)


def test_elimination_is_marked_in_review_and_cached(monkeypatch, state):
    request = elimination_request()
    state = replace(
        state, speaker_candidates=("Alex", "Casey"), speaker_utterances=request.utterances
    )
    load_fixture(monkeypatch, state)
    client = Mock()
    client.identify.return_value = elimination_result()
    loader = SpeakerSuggestionLoader(client, people("Alex"))
    loaded = loader(state.meeting_directory)
    assert loaded.speaker_suggestions == {"A": "Alex", "B": "Casey"}
    assert loaded.speaker_evidence["B"] == "By elimination (verify): The launch is ready."
    assert loader(state.meeting_directory) == loaded
    client.identify.assert_called_once()

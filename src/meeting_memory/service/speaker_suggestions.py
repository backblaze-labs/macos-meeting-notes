"""Read-only Claude speaker proposals using local known-person context."""

from __future__ import annotations

import threading
from collections import Counter
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Protocol

from meeting_memory.service.transcript_review import load_speaker_review
from meeting_memory.types.speakers import (
    KnownSpeaker,
    SpeakerIdentificationRequest,
    SpeakerIdentificationResult,
    SpeakerSuggestion,
)
from meeting_memory.types.transcript import SpeakerReviewState


class SpeakerIdentificationClient(Protocol):
    def identify(self, request: SpeakerIdentificationRequest) -> SpeakerIdentificationResult:
        """Propose assignments from supplied local text and known-person context."""


class SpeakerSuggestionLoader:
    def __init__(
        self,
        client: SpeakerIdentificationClient,
        people: tuple[KnownSpeaker, ...],
        *,
        enabled: Callable[[], bool] = lambda: True,
    ) -> None:
        self._client = client
        self._people = {person.name: person for person in people}
        self._enabled = enabled
        self._cache: dict[tuple, tuple[SpeakerSuggestion, ...]] = {}
        self._lock = threading.Lock()

    def __call__(self, path: Path) -> SpeakerReviewState:
        state = load_speaker_review(path)
        if state.speaker_status == "confirmed" and state.speaker_aliases:
            return state
        candidates = tuple(dict.fromkeys(state.speaker_candidates))
        if not candidates or not set(candidates) <= self._people.keys():
            return replace(state, suggestion_message="Assign names manually for unknown attendees.")
        if not state.speaker_utterances:
            return replace(state, suggestion_message="No diarized text available for suggestions.")
        if not self._enabled():
            return replace(state, suggestion_message="Notes is paused. Assign names manually.")
        request = SpeakerIdentificationRequest(
            tuple(turn for turn in state.speaker_utterances if turn.label in state.speaker_labels),
            tuple(self._people[name] for name in candidates),
        )
        key = (str(state.transcript_path), review_identity(state), request.people)
        with self._lock:
            cached = self._cache.get(key)
        if cached is not None:
            return self._with_suggestions(state, cached)
        try:
            result = self._client.identify(request)
            suggestions = validate_suggestions(result, request)
            current = load_speaker_review(path)
            if review_identity(current) != review_identity(state):
                return replace(
                    current, suggestion_message="Transcript changed. Review current labels."
                )
        except Exception:
            return replace(
                state, suggestion_message="Suggestions unavailable. Assign names manually."
            )
        if not self._enabled():
            return replace(state, suggestion_message="Notes is paused. Assign names manually.")
        if suggestions:
            with self._lock:
                self._cache[key] = suggestions
            return self._with_suggestions(state, suggestions)
        return replace(state, suggestion_message="No clear assignments. Assign names manually.")

    @staticmethod
    def _with_suggestions(
        state: SpeakerReviewState, suggestions: tuple[SpeakerSuggestion, ...]
    ) -> SpeakerReviewState:
        return replace(
            state,
            speaker_suggestions={item.label: item.name for item in suggestions},
            speaker_evidence={item.label: item.evidence for item in suggestions},
            suggestion_message="Suggested by Claude Haiku. Verify each name before confirming.",
        )


def validate_suggestions(
    result: SpeakerIdentificationResult,
    request: SpeakerIdentificationRequest,
) -> tuple[SpeakerSuggestion, ...]:
    """Accept unique candidate names with exact evidence spoken by that label."""
    names = {person.name for person in request.people}
    turns = request.utterances
    proposed = tuple(
        item
        for item in result.suggestions
        if item.name in names
        and bool(item.evidence.strip())
        and any(turn.label == item.label and item.evidence in turn.text for turn in turns)
    )
    labels = Counter(item.label for item in proposed)
    people = Counter(item.name for item in proposed)
    return tuple(item for item in proposed if labels[item.label] == 1 and people[item.name] == 1)


def review_identity(state: SpeakerReviewState) -> tuple:
    return (
        state.assemblyai_id,
        state.speaker_labels,
        state.speaker_candidates,
        tuple(sorted(state.speaker_aliases.items())),
        state.speaker_status,
        state.speaker_utterances,
    )

"""Read-only Claude speaker proposals using local known-person context."""

from __future__ import annotations

import json
import logging
import threading
from collections import Counter
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Protocol

from meeting_memory.service.transcript_review import load_speaker_review
from meeting_memory.types.speakers import (
    KnownSpeaker,
    SpeakerIdentificationError,
    SpeakerIdentificationRequest,
    SpeakerIdentificationResult,
    SpeakerSuggestion,
)
from meeting_memory.types.transcript import SpeakerReviewState

LOGGER = logging.getLogger(__name__)


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
        self._people = people
        self._enabled = enabled
        self._cache: dict[tuple, tuple[SpeakerSuggestion, ...]] = {}
        self._lock = threading.Lock()

    def __call__(self, path: Path) -> SpeakerReviewState:
        state = load_speaker_review(path)
        if state.speaker_status == "confirmed" and state.speaker_aliases:
            return state
        candidates = tuple(dict.fromkeys(state.speaker_candidates))
        people = self._candidate_people(candidates)
        if not people:
            return replace(state, suggestion_message="No named attendees. Assign names manually.")
        if not state.speaker_utterances:
            return replace(state, suggestion_message="No diarized text available for suggestions.")
        if not self._enabled():
            return replace(state, suggestion_message="Notes is paused. Assign names manually.")
        request = SpeakerIdentificationRequest(
            tuple(turn for turn in state.speaker_utterances if turn.label in state.speaker_labels),
            people,
            allow_elimination=len(people) == len(candidates),
        )
        key = (str(state.transcript_path), review_identity(state), request.people)
        with self._lock:
            cached = self._cache.get(key)
        if cached is not None:
            return self._with_suggestions(state, cached)
        try:
            result = self._client.identify(request)
            suggestions = validate_suggestions(result, request)
            LOGGER.info(
                "Speaker suggestions completed labels=%s proposed=%s accepted=%s",
                len(state.speaker_labels),
                len(result.suggestions),
                len(suggestions),
            )
            LOGGER.info(
                "Speaker proposal diagnostics meeting=%s proposals=%s",
                json.dumps(state.meeting_directory.name, ensure_ascii=True),
                json.dumps(
                    [
                        {
                            "label": item.label[:200],
                            "name": item.name[:200],
                            "evidence": item.evidence[:2000],
                            "evidence_truncated": len(item.evidence) > 2000,
                            "accepted": item in suggestions,
                            "method": item.method,
                        }
                        for item in result.suggestions[:100]
                    ],
                    ensure_ascii=True,
                ),
            )
            current = load_speaker_review(path)
            if review_identity(current) != review_identity(state):
                return replace(
                    current, suggestion_message="Transcript changed. Review current labels."
                )
        except SpeakerIdentificationError as exc:
            return replace(state, suggestion_message=str(exc))
        except Exception as exc:
            LOGGER.warning("Speaker review unavailable error_type=%s", type(exc).__name__)
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

    def _candidate_people(self, candidates: tuple[str, ...]) -> tuple[KnownSpeaker, ...]:
        """Resolve exact local aliases, retaining named attendees without a profile."""
        people: dict[str, KnownSpeaker] = {}
        for candidate in candidates:
            matches = tuple(
                person
                for person in self._people
                if candidate.casefold()
                in {value.casefold() for value in (person.name, *person.matches)}
            )
            if len(matches) > 1:
                continue
            person = matches[0] if matches else KnownSpeaker(candidate)
            if "@" not in person.name:
                people[person.name] = person
        return tuple(people.values())

    @staticmethod
    def _with_suggestions(
        state: SpeakerReviewState, suggestions: tuple[SpeakerSuggestion, ...]
    ) -> SpeakerReviewState:
        return replace(
            state,
            speaker_suggestions={item.label: item.name for item in suggestions},
            speaker_evidence={
                item.label: (
                    f"By elimination (verify): {item.evidence}"
                    if item.method == "elimination"
                    else item.evidence
                )
                for item in suggestions
            },
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
        and item.method in {"direct", "elimination"}
        and bool(item.evidence.strip())
        and any(turn.label == item.label and item.evidence in turn.text for turn in turns)
    )
    labels = Counter(item.label for item in proposed)
    people = Counter(item.name for item in proposed)
    unique = tuple(item for item in proposed if labels[item.label] == 1 and people[item.name] == 1)
    direct = tuple(item for item in unique if item.method == "direct")
    remaining_names = names - {item.name for item in direct}
    remaining_labels = {
        turn.label for turn in turns if turn.label.casefold() not in {"unknown", "speaker unknown"}
    } - {item.label for item in direct}
    elimination = tuple(item for item in unique if item.method == "elimination")
    return tuple(
        item
        for item in unique
        if item.method == "direct"
        or (
            request.allow_elimination
            and len(elimination) == 1
            and bool(direct)
            and remaining_names == {item.name}
            and remaining_labels == {item.label}
        )
    )


def review_identity(state: SpeakerReviewState) -> tuple:
    return (
        state.transcription_provider,
        state.transcription_attempt_id,
        state.assemblyai_id,
        state.speaker_labels,
        state.speaker_candidates,
        tuple(sorted(state.speaker_aliases.items())),
        state.speaker_status,
        state.speaker_utterances,
    )

"""Read-only people drafts and narrow compare-and-swap roster edits."""

import json
import logging
import threading
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Protocol

from meeting_memory.config.settings import Settings
from meeting_memory.service.preference_store import PreferencesConflictError, PreferenceStore
from meeting_memory.service.speaker_history import harvest_speaker_history
from meeting_memory.service.speaker_knowledge_offers import KnowledgeOfferStore
from meeting_memory.types.configuration import PreferenceKey, PreferenceSnapshot, PreferenceValue
from meeting_memory.types.speaker_knowledge import KnowledgeDraft, PersonHistory, PersonTopic
from meeting_memory.types.speakers import KnownSpeaker

LOGGER = logging.getLogger(__name__)


class TopicsClient(Protocol):
    def describe(self, people: tuple[PersonHistory, ...]) -> tuple[PersonTopic, ...]: ...


class SpeakerKnowledgeService:
    def __init__(
        self, settings: Settings, *, store=None, topics=None, enabled=lambda: True, offers=None
    ):
        self._settings = settings
        self._store = store if store is not None else PreferenceStore.default()
        self._topics: TopicsClient | None = topics
        self._enabled = enabled
        self._offers = (
            offers
            if offers is not None
            else KnowledgeOfferStore(self._store.path.parent / "speaker-onboarding.json")
        )
        self._bindings: dict[str, PreferenceSnapshot] = {}
        self._lock = threading.Lock()

    @property
    def topics_available(self) -> bool:
        return self._topics is not None and self._enabled()

    def draft(self, *, include_history: bool = False) -> KnowledgeDraft:
        snapshot = self._store.load_snapshot()
        stored = Settings.parse_known_speakers(
            snapshot.preferences.value_for(PreferenceKey.KNOWN_SPEAKERS) or "[]"
        )
        history = harvest_speaker_history(self._settings.meetings_dir_path)
        people = {person.name: person for person in stored}
        if snapshot.preferences.value_for(PreferenceKey.KNOWN_SPEAKERS) is None:
            for person in self._settings.known_speakers:
                people.setdefault(person.name, person)
        if include_history:
            for person in history.people:
                people.setdefault(person.name, KnownSpeaker(person.name))
        token = uuid.uuid4().hex
        with self._lock:
            self._bindings.clear()
            self._bindings[token] = snapshot
        return KnowledgeDraft(
            token, tuple(people.values()), history, history_included=include_history
        )

    def cancel(self, token: str) -> None:
        with self._lock:
            self._bindings.pop(token, None)

    def suggest_topics(self, draft: KnowledgeDraft) -> KnowledgeDraft:
        if not self.topics_available:
            return replace(draft, message="Notes unavailable or paused. Names-only draft retained.")
        names = {person.name for person in draft.people if not person.description}
        supplied = tuple(
            person for person in draft.history.people if person.name in names and person.quotes
        )
        if not supplied:
            return replace(
                draft, message="No confirmed work excerpts for these names. Edit topics manually."
            )
        try:
            proposals = self._topics.describe(supplied)
            if not self._enabled():
                return replace(draft, message="Notes paused. Names-only draft retained.")
            quotes = {person.name: person.quotes for person in supplied}
            counts = {name: sum(p.name == name for p in proposals) for name in quotes}
            descriptions = {
                p.name: p.description
                for p in proposals
                if p.name in quotes
                and counts[p.name] == 1
                and 0 < len(p.description.strip()) <= 300
                and bool(p.evidence.strip())
                and any(p.evidence in q for q in quotes[p.name])
            }
            people = tuple(
                replace(p, description=descriptions.get(p.name, p.description))
                for p in draft.people
            )
            return replace(
                draft, people=people, message="Proposed topics. Edit and verify before saving."
            )
        except Exception as exc:
            LOGGER.warning("People topics unavailable error_type=%s", type(exc).__name__)
            return replace(draft, message="Topic suggestions unavailable. Edit or save names only.")

    def save(self, draft: KnowledgeDraft) -> str:
        with self._lock:
            snapshot = self._bindings.pop(draft.token, None)
        if snapshot is None:
            return "People draft expired. Reopen Known Speakers."
        if len({person.name.casefold() for person in draft.people}) != len(draft.people):
            return "Names differ only by case. Review them explicitly before saving."
        raw = json.dumps(
            [
                {"name": p.name, "matches": p.matches, "description": p.description}
                for p in draft.people
            ]
        )
        values = tuple(
            v for v in snapshot.preferences.values if v.key is not PreferenceKey.KNOWN_SPEAKERS
        )
        preferences = replace(
            snapshot.preferences,
            values=(*values, PreferenceValue(PreferenceKey.KNOWN_SPEAKERS, raw)),
        )
        try:
            self._store.compare_and_swap(snapshot, preferences)
        except PreferencesConflictError:
            return (
                "Configuration changed elsewhere. Reopen Known Speakers; nothing was overwritten."
            )
        except Exception:
            return "Save could not be confirmed. Reopen Known Speakers to inspect current values."
        return (
            "Known Speakers saved. Quit and reopen Meeting Memory to use the updated base. "
            "This saves only the roster. Any process environment override still takes precedence."
        )

    def offer(self, path: Path | None = None) -> tuple[str, ...]:
        snapshot = self._store.load_snapshot()
        stored = Settings.parse_known_speakers(
            snapshot.preferences.value_for(PreferenceKey.KNOWN_SPEAKERS) or "[]"
        )
        current = (
            stored
            if snapshot.preferences.value_for(PreferenceKey.KNOWN_SPEAKERS) is not None
            else self._settings.known_speakers
        )
        known = {p.name for p in current}
        if path is None and known:
            return ()
        history = harvest_speaker_history(self._settings.meetings_dir_path, only=path)
        names = tuple(p.name for p in history.people if p.name not in known)
        return names if self._offers.claim(names, initial=path is None) else ()

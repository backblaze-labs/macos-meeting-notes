"""Main-thread people onboarding with worker storage and explicit egress."""

import logging
from dataclasses import replace

from meeting_memory.types.events import NotifyEvent
from meeting_memory.types.speaker_knowledge import (
    KnowledgeDraftReady,
    KnowledgeFinished,
    KnowledgeOffer,
)
from meeting_memory.ui.preference_forms import open_known_speakers_form
from meeting_memory.ui.speaker_knowledge_forms import choose_history_action, choose_topics_action

KNOWN_SPEAKERS_LABEL = "Known Speakers..."


class SpeakerKnowledgeUI:
    def __init__(self, controller, rumps, *, service=None, service_factory=None):
        self._controller = controller
        self._rumps = rumps
        self._service = service
        self._service_factory = service_factory
        self._busy = False

    def startup(self):
        if self._service is not None:
            self._worker(self._offer, offer_only=True)

    def after_review(self, path):
        if self._service is not None:
            self._worker(lambda: self._offer(path), offer_only=True)

    def _offer(self, path=None):
        names = self._service.offer(path)
        if names:
            self._controller.event_queue.put(KnowledgeOffer(names, initial=path is None))

    def open(self, *, include_history=False):
        if self._busy or (self._service is None and self._service_factory is None):
            return
        self._busy = True

        def load():
            if self._service is None:
                self._service = self._service_factory()
            self._controller.event_queue.put(
                KnowledgeDraftReady(self._service.draft(include_history=include_history))
            )

        self._worker(load)

    def handle_event(self, event):
        if isinstance(event, KnowledgeOffer):
            body = (
                "Build an editable draft from confirmed names in previous meetings."
                if event.initial
                else "New confirmed names can help future speaker review."
            )
            self._controller.event_queue.put(
                NotifyEvent(
                    "Create my people base" if event.initial else "Add people to Known Speakers",
                    body,
                    action="known_speakers",
                    action_label="Known Speakers",
                )
            )
            return True
        if isinstance(event, KnowledgeFinished):
            self._busy = False
            self._rumps.alert(title="Known Speakers", message=event.message)
            return True
        if not isinstance(event, KnowledgeDraftReady):
            return False
        draft = event.draft
        try:
            if not draft.history_included and not draft.message and draft.history.people:
                action = choose_history_action(draft)
                if action == "cancel":
                    self._cancel(draft)
                    return True
                if action == "history":
                    self._cancel(draft)
                    self.open(include_history=True)
                    return True
            people = self._edit_people(
                draft.people,
                message=(
                    draft.message
                    or f"Local draft from {draft.history.meetings} confirmed named meetings. "
                    "Existing matches and descriptions are preserved. "
                    "Keep distinct names separate; "
                    "add Calendar aliases/emails only when you know the match."
                ),
                ok_label="Save" if draft.message else "Continue",
            )
            if people is None:
                self._cancel(draft)
                return True
            draft = replace(draft, people=people)
            action = (
                "save"
                if draft.message
                else choose_topics_action(draft, self._service.topics_available)
            )
            if action == "cancel":
                self._cancel(draft)
            elif action == "topics":
                self._worker(
                    lambda: self._controller.event_queue.put(
                        KnowledgeDraftReady(self._service.suggest_topics(draft))
                    )
                )
            else:
                self._worker(
                    lambda: self._controller.event_queue.put(
                        KnowledgeFinished(self._service.save(draft))
                    )
                )
        except Exception:
            self._cancel(draft)
            self._rumps.alert(
                title="Known Speakers", message="Draft could not be opened. Nothing was saved."
            )
        return True

    def _edit_people(self, people, **kwargs):
        while True:
            try:
                return open_known_speakers_form(people, **kwargs)
            except ValueError:
                self._rumps.alert(
                    title="Review people draft",
                    message="Names must be unique, including case. Edit ambiguous names explicitly "
                    "and keep descriptions within 300 characters. Nothing has been saved.",
                )

    def _cancel(self, draft):
        self._service.cancel(draft.token)
        self._busy = False

    def _worker(self, work, *, offer_only=False):
        def run():
            try:
                work()
            except Exception as exc:
                if offer_only:
                    logging.getLogger(__name__).warning(
                        "People offer unavailable error_type=%s", type(exc).__name__
                    )
                    return
                self._controller.event_queue.put(
                    KnowledgeFinished("People base unavailable. Try Known Speakers again.")
                )

        try:
            self._controller.thread_factory(target=run, daemon=True).start()
        except Exception:
            if offer_only:
                return
            self._busy = False
            self._controller.event_queue.put(
                KnowledgeFinished("People base worker could not start. Try again.")
            )

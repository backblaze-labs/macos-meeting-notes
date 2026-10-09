"""Visible onboarding/action wiring with no persistence before confirmation."""

from types import SimpleNamespace
from unittest.mock import Mock

from meeting_memory.types.events import NotifyEvent
from meeting_memory.types.speaker_knowledge import (
    KnowledgeDraft,
    KnowledgeDraftReady,
    KnowledgeOffer,
    SpeakerHistory,
)
from meeting_memory.types.speakers import KnownSpeaker
from meeting_memory.ui.notification_actions import dispatch_notification
from meeting_memory.ui.speaker_knowledge import SpeakerKnowledgeUI
from meeting_memory.ui.speaker_review_flow import SpeakerReviewFlow


def ui(service):
    queue = []
    controller = SimpleNamespace(
        event_queue=SimpleNamespace(put=queue.append),
        thread_factory=lambda target, **_k: SimpleNamespace(start=target),
    )
    return SpeakerKnowledgeUI(controller, Mock(), service=service), queue


def test_startup_offer_and_notification_action_open_visible_editor():
    service = Mock()
    service.offer.return_value = ("Alex",)
    window, queue = ui(service)
    window.startup()
    assert queue == [KnowledgeOffer(("Alex",), True)]
    window.handle_event(queue.pop())
    assert isinstance(queue[0], NotifyEvent) and queue[0].action == "known_speakers"
    app = SimpleNamespace(people_base=Mock())
    dispatch_notification(app, {"action": "known_speakers"})
    app.people_base.open.assert_called_once_with(include_history=True)


def test_cancel_draft_does_not_save_or_request_topics(monkeypatch):
    service = Mock()
    window, _ = ui(service)
    monkeypatch.setattr(
        "meeting_memory.ui.speaker_knowledge.open_known_speakers_form", lambda *a, **k: None
    )
    draft = KnowledgeDraft("token", (KnownSpeaker("Alex"),), SpeakerHistory())
    assert window.handle_event(KnowledgeDraftReady(draft))
    service.cancel.assert_called_once_with("token")
    service.save.assert_not_called()
    service.suggest_topics.assert_not_called()


def test_names_only_path_saves_editable_draft_without_topic_request(monkeypatch):
    service = Mock()
    service.topics_available = False
    window, _ = ui(service)
    people = (KnownSpeaker("Alex", ("explicit@example.com",), "User context"),)
    monkeypatch.setattr(
        "meeting_memory.ui.speaker_knowledge.open_known_speakers_form", lambda *a, **k: people
    )
    monkeypatch.setattr(
        "meeting_memory.ui.speaker_knowledge.choose_topics_action", lambda *_a: "save"
    )
    draft = KnowledgeDraft("token", (), SpeakerHistory())
    window.handle_event(KnowledgeDraftReady(draft))
    assert service.save.call_args.args[0].people == people
    service.suggest_topics.assert_not_called()


def test_post_review_offer_occurs_after_notes_started():
    calls = []
    controller = SimpleNamespace(generate_notes=lambda path: calls.append(("notes", path)))
    flow = SpeakerReviewFlow(
        controller, Mock(), Mock(), after_review=lambda path: calls.append(("offer", path))
    )
    flow._generate_and_offer("meeting")
    assert calls == [("notes", "meeting"), ("offer", "meeting")]


def test_post_review_offer_survives_notes_unavailability():
    import pytest

    calls = []

    def unavailable(_path):
        raise RuntimeError("Notes unavailable")

    flow = SpeakerReviewFlow(
        SimpleNamespace(generate_notes=unavailable),
        Mock(),
        Mock(),
        after_review=lambda path: calls.append(path),
    )
    with pytest.raises(RuntimeError):
        flow._generate_and_offer("meeting")
    assert calls == ["meeting"]


def test_background_offer_failure_does_not_mutate_draft_or_show_modal():
    service = Mock()
    service.offer.side_effect = OSError("private path")
    window, queue = ui(service)
    window._busy = True
    window.startup()
    assert window._busy and queue == []
    window._rumps.alert.assert_not_called()


def test_many_person_native_form_scrolls_from_first_row(monkeypatch):
    import sys

    from speaker_review_fakes import FakeAppKit

    from meeting_memory.ui.preference_forms import open_known_speakers_form

    appkit = FakeAppKit([1000])
    monkeypatch.setitem(sys.modules, "AppKit", appkit)
    people = tuple(KnownSpeaker(f"Person {i}", (f"alias{i}",), "Work topics") for i in range(30))
    assert open_known_speakers_form(people) == people
    scroll = appkit.alerts[0].accessory
    assert scroll.frame == (0, 0, 720, 560)
    assert scroll.vertical_scroller is True
    assert scroll.scrolled_to == (0, 104 + 33 * 66 - 560)
    assert appkit.alerts[0].buttons == ["Save", "Cancel"]


def test_optional_topics_requires_explicit_action_and_does_not_save(monkeypatch):
    service = Mock()
    service.topics_available = True
    window, _ = ui(service)
    people = (KnownSpeaker("Alex"),)
    monkeypatch.setattr(
        "meeting_memory.ui.speaker_knowledge.open_known_speakers_form", lambda *a, **k: people
    )
    monkeypatch.setattr(
        "meeting_memory.ui.speaker_knowledge.choose_topics_action", lambda *_a: "topics"
    )
    draft = KnowledgeDraft("token", people, SpeakerHistory(), history_included=True)
    window.handle_event(KnowledgeDraftReady(draft))
    service.suggest_topics.assert_called_once_with(draft)
    service.save.assert_not_called()


def test_names_only_setup_menu_has_real_known_people_action():
    from tray_fakes import FakeRumps

    from meeting_memory.ui.sidebar_view_model import ConfigurationActions
    from meeting_memory.ui.submenus import configuration_submenu

    opened = []
    actions = ConfigurationActions(Mock(), Mock(), Mock(), Mock(), lambda: opened.append(True))
    submenu = configuration_submenu(FakeRumps(), actions, notes_prompt_available=False)
    item = next(
        item for item in submenu.items if item is not None and item.title == "Known Speakers..."
    )
    item.callback(None)
    assert opened == [True]


def test_history_choice_does_not_force_import_for_normal_editor(monkeypatch):
    import sys

    from speaker_review_fakes import FakeAppKit

    from meeting_memory.ui.speaker_knowledge_forms import choose_history_action

    appkit = FakeAppKit([1000])
    monkeypatch.setitem(sys.modules, "AppKit", appkit)
    assert choose_history_action(KnowledgeDraft("t", (), SpeakerHistory())) == "edit"
    assert appkit.alerts[0].buttons[:2] == ["Edit Current Base", "Create from Previous Meetings"]


def test_ambiguous_name_feedback_allows_editing_same_draft(monkeypatch):
    service = Mock()
    service.topics_available = False
    window, _ = ui(service)
    people = (KnownSpeaker("Alex"), KnownSpeaker("alex"))
    edits = iter(
        (ValueError("case collision"), (KnownSpeaker("Alex"), KnownSpeaker("Alex Rivera")))
    )

    def edit(*_a, **_k):
        result = next(edits)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr("meeting_memory.ui.speaker_knowledge.open_known_speakers_form", edit)
    monkeypatch.setattr(
        "meeting_memory.ui.speaker_knowledge.choose_topics_action", lambda *_a: "save"
    )
    window.handle_event(KnowledgeDraftReady(KnowledgeDraft("token", people, SpeakerHistory())))
    assert [p.name for p in service.save.call_args.args[0].people] == ["Alex", "Alex Rivera"]
    assert "unique" in window._rumps.alert.call_args.kwargs["message"]

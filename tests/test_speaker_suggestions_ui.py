"""Speaker proposal presentation requires explicit confirmation."""

import sys
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

from speaker_review_fakes import FakeAppKit
from test_speaker_review_ui import FakeActions, FakeRumps, _state

from meeting_memory.types.events import SpeakerReviewReady
from meeting_memory.ui.speaker_review import (
    SpeakerReviewActions,
    _prompt_aliases_appkit,
    _review_message,
    open_speaker_review_window,
)
from meeting_memory.ui.speaker_review_flow import SpeakerReviewFlow


def test_suggested_defaults_are_shown_and_can_be_cancelled(monkeypatch, tmp_path):
    appkit = FakeAppKit(responses=[1002])
    monkeypatch.setitem(sys.modules, "AppKit", appkit)
    state = replace(
        _state(tmp_path),
        speaker_suggestions={"Speaker A": "Alex", "Speaker B": "Casey"},
        suggestion_message="Verify before confirming.",
    )
    actions = FakeActions(state)
    assert not open_speaker_review_window(
        tmp_path,
        SpeakerReviewActions(
            actions.load_review,
            actions.confirm_aliases,
            lambda _p: None,
            actions.generate_notes,
        ),
        rumps_module=FakeRumps(),
    )
    assert actions.confirmed == [] and actions.notes == []
    assert "Verify before confirming" in _review_message(state)


def test_existing_manual_alias_overrides_proposal(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "AppKit", FakeAppKit([1000]))
    state = replace(
        _state(tmp_path),
        speaker_aliases={"Speaker A": "Drew"},
        speaker_suggestions={"Speaker A": "Alex", "Speaker B": "Casey"},
    )
    aliases = _prompt_aliases_appkit(state, lambda _p: None, lambda _p: None)
    assert aliases == {"Speaker A": "Drew", "Speaker B": "Casey"}


def test_background_flow_presents_only_on_ready_event(monkeypatch, tmp_path):
    state = _state(tmp_path)
    queue = Mock()
    worker = Mock()
    controller = SimpleNamespace(
        event_queue=queue,
        thread_factory=Mock(return_value=worker),
        load_speaker_review=Mock(return_value=state),
        confirm_speaker_aliases=Mock(),
        keep_speaker_labels=Mock(),
        generate_notes=Mock(),
    )
    presented = Mock()
    monkeypatch.setattr(
        "meeting_memory.ui.speaker_review_flow.open_speaker_review_window", presented
    )
    monkeypatch.setattr(
        "meeting_memory.ui.speaker_review_flow.load_speaker_review", lambda _p: state
    )
    flow = SpeakerReviewFlow(controller, FakeRumps(), Mock())
    flow.open(tmp_path)
    flow.open(tmp_path)
    controller.thread_factory.assert_called_once()
    worker.start.assert_called_once()
    controller.load_speaker_review.assert_not_called()
    presented.assert_not_called()
    controller.thread_factory.call_args.kwargs["target"](tmp_path)
    event = queue.put.call_args.args[0]
    assert isinstance(event, SpeakerReviewReady)
    flow.handle_event(event)
    presented.assert_called_once()
    controller.confirm_speaker_aliases.assert_not_called()
    controller.generate_notes.assert_not_called()


def test_confirm_names_applies_suggestions_only_after_user_click(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "AppKit", FakeAppKit([1000]))
    state = replace(
        _state(tmp_path), speaker_suggestions={"Speaker A": "Alex", "Speaker B": "Casey"}
    )
    actions = FakeActions(state)
    assert open_speaker_review_window(
        tmp_path,
        SpeakerReviewActions(
            actions.load_review,
            actions.confirm_aliases,
            lambda _p: None,
            actions.generate_notes,
        ),
        rumps_module=FakeRumps(),
    )
    assert actions.confirmed == [(tmp_path, {"Speaker A": "Alex", "Speaker B": "Casey"})]
    assert actions.notes == [tmp_path]


def test_main_thread_drops_proposals_if_review_changed_since_worker(monkeypatch, tmp_path):
    original = replace(
        _state(tmp_path), speaker_suggestions={"Speaker A": "Alex"}, assemblyai_id="old"
    )
    current = replace(original, assemblyai_id="new", speaker_suggestions={})
    monkeypatch.setattr(
        "meeting_memory.ui.speaker_review_flow.load_speaker_review", lambda _p: current
    )
    presented = Mock()
    monkeypatch.setattr(
        "meeting_memory.ui.speaker_review_flow.open_speaker_review_window", presented
    )
    controller = SimpleNamespace(
        event_queue=Mock(),
        confirm_speaker_aliases=Mock(),
        keep_speaker_labels=Mock(),
        generate_notes=Mock(),
    )
    flow = SpeakerReviewFlow(controller, FakeRumps(), Mock())
    flow.handle_event(SpeakerReviewReady(original))
    actions = presented.call_args.args[1]
    assert actions.load_review(tmp_path) is current
    assert actions.load_review(tmp_path).speaker_suggestions == {}

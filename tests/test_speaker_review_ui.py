"""Tests for the speaker review UI flow."""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass, field, replace
from pathlib import Path

from meeting_memory.types.transcript import SpeakerReviewState
from meeting_memory.ui.speaker_review import (
    FULL_TRANSCRIPT_RESPONSE,
    OPEN_MARKDOWN_RESPONSE,
    SPEAKER_REVIEW_MAX_HEIGHT,
    SpeakerReviewActions,
    _prompt_aliases_appkit,
    _review_message,
    open_speaker_review_window,
)


def test_speaker_review_window_confirms_aliases_and_offers_notes(tmp_path: Path) -> None:
    rumps = FakeRumps()
    actions = FakeActions(_state(tmp_path))

    opened = open_speaker_review_window(
        tmp_path,
        SpeakerReviewActions(
            load_review=actions.load_review,
            confirm_aliases=actions.confirm_aliases,
            generate_notes=actions.generate_notes,
        ),
        rumps_module=rumps,
        prompt_aliases=lambda _state: {"Speaker A": "Alex", "Speaker B": "Casey"},
    )

    assert opened is True
    assert actions.loaded == [tmp_path]
    assert actions.confirmed == [(tmp_path, {"Speaker A": "Alex", "Speaker B": "Casey"})]
    assert actions.notes == [tmp_path]
    assert rumps.alerts == []


def test_speaker_review_window_generates_notes_without_second_prompt(tmp_path: Path) -> None:
    actions = FakeActions(_state(tmp_path))

    opened = open_speaker_review_window(
        tmp_path,
        SpeakerReviewActions(
            load_review=actions.load_review,
            confirm_aliases=actions.confirm_aliases,
            generate_notes=actions.generate_notes,
        ),
        rumps_module=FakeRumps(),
        prompt_aliases=lambda _state: {"Speaker A": "Alex", "Speaker B": "Casey"},
    )

    assert opened is True
    assert actions.notes == [tmp_path]


def test_speaker_review_window_stops_when_cancelled(tmp_path: Path) -> None:
    actions = FakeActions(_state(tmp_path))

    opened = open_speaker_review_window(
        tmp_path,
        SpeakerReviewActions(
            load_review=actions.load_review,
            confirm_aliases=actions.confirm_aliases,
            generate_notes=actions.generate_notes,
        ),
        rumps_module=FakeRumps(),
        prompt_aliases=lambda _state: None,
    )

    assert opened is False
    assert actions.confirmed == []


def test_speaker_review_message_omits_repeated_longest_lines(tmp_path: Path) -> None:
    message = _review_message(_state(tmp_path))

    assert "Detected speakers: Speaker A, Speaker B" in message
    assert "Candidates: Alex, Casey, Drew, Blair" in message
    assert "Longest line" not in message


def test_appkit_review_actions_return_to_selector(monkeypatch, tmp_path: Path) -> None:
    fake_appkit = FakeAppKit(
        responses=[OPEN_MARKDOWN_RESPONSE, FULL_TRANSCRIPT_RESPONSE, 1000]
    )
    monkeypatch.setitem(sys.modules, "AppKit", fake_appkit)
    opened = []
    expanded = []

    state = _state(tmp_path)
    state.speaker_aliases.update({"Speaker A": "Alex", "Speaker B": "Casey"})

    aliases = _prompt_aliases_appkit(
        state,
        open_conversation=lambda path: opened.append(path),
        show_transcript=lambda path: expanded.append(path),
    )

    assert aliases == {"Speaker A": "Alex", "Speaker B": "Casey"}
    assert opened == [tmp_path / "transcript.md"]
    assert expanded == [tmp_path / "transcript.md"]


def test_appkit_review_scrolls_many_speakers(monkeypatch, tmp_path: Path) -> None:
    fake_appkit = FakeAppKit(responses=[1000])
    monkeypatch.setitem(sys.modules, "AppKit", fake_appkit)
    labels = tuple(f"Speaker {index}" for index in range(12))
    state = replace(
        _state(tmp_path),
        speaker_labels=labels,
        speaker_longest_lines=dict.fromkeys(labels, "Line from the meeting."),
    )

    _prompt_aliases_appkit(state, lambda _path: None, lambda _path: None)

    scroll_view = fake_appkit.alerts[0].accessory
    content_height = 62 + len(labels) * 82
    assert (scroll_view.frame, scroll_view.document_view.frame) == (
        (0, 0, 640, SPEAKER_REVIEW_MAX_HEIGHT),
        (0, 0, 640, content_height),
    )
    assert scroll_view.vertical_scroller is True
    assert scroll_view.horizontal_scroller is False
    assert scroll_view.scrolled_to == (0, content_height - SPEAKER_REVIEW_MAX_HEIGHT)


def _state(tmp_path: Path) -> SpeakerReviewState:
    return SpeakerReviewState(
        meeting_directory=tmp_path,
        transcript_path=tmp_path / "transcript.md",
        speaker_labels=("Speaker A", "Speaker B"),
        speaker_candidates=("Alex", "Casey", "Drew", "Blair"),
        speaker_aliases={},
        speaker_status="needs_review",
        speaker_longest_lines={
            "Speaker A": "I can own the launch plan.",
            "Speaker B": "I will update the deck.",
        },
    )


@dataclass
class FakeActions:
    state: SpeakerReviewState
    loaded: list[Path] = field(default_factory=list)
    confirmed: list[tuple[Path, dict[str, str]]] = field(default_factory=list)
    notes: list[Path] = field(default_factory=list)

    def load_review(self, path: Path) -> SpeakerReviewState:
        self.loaded.append(path)
        return self.state

    def confirm_aliases(self, path: Path, aliases: dict[str, str]) -> Path:
        self.confirmed.append((path, aliases))
        return path / "transcript.md"

    def generate_notes(self, path: Path) -> None:
        self.notes.append(path)


@dataclass
class FakeRumps:
    alert_responses: list[int] = field(default_factory=list)
    alerts: list[dict[str, object]] = field(default_factory=list)

    def alert(self, **kwargs) -> int:
        self.alerts.append(kwargs)
        if self.alert_responses:
            return self.alert_responses.pop(0)
        return 0


class FakeAppKit(types.SimpleNamespace):
    def __init__(self, responses: list[int]) -> None:
        self.alerts: list[FakeAlert] = []
        super().__init__(
            NSAlert=_FakeAlertFactory(responses, self.alerts),
            NSFont=types.SimpleNamespace(systemFontOfSize_=lambda _size: object()),
            NSMakePoint=lambda *args: args,
            NSMakeRect=lambda *args: args,
            NSPopUpButton=FakePopUpButton,
            NSScrollView=FakeScrollView,
            NSTextField=FakeTextField,
            NSView=FakeView,
        )


class _FakeAlloc:
    @classmethod
    def alloc(cls):
        return cls()


class _FakeAlertFactory:
    def __init__(self, responses: list[int], alerts: list[FakeAlert]) -> None:
        self.responses = responses
        self.alerts = alerts

    def alloc(self):
        alert = FakeAlert(self.responses)
        self.alerts.append(alert)
        return alert


class FakeAlert:
    def __init__(self, responses: list[int]) -> None:
        self.responses = responses
        self.accessory = None

    def init(self):
        return self

    def setMessageText_(self, _text) -> None:
        pass

    def setInformativeText_(self, _text) -> None:
        pass

    def addButtonWithTitle_(self, _title) -> None:
        pass

    def setAccessoryView_(self, view) -> None:
        self.accessory = view

    def runModal(self) -> int:
        return self.responses.pop(0)


class FakeView(_FakeAlloc):
    def initWithFrame_(self, frame):
        self.frame = frame
        return self
    def addSubview_(self, _view) -> None:
        pass


class FakeScrollView(_FakeAlloc):
    def initWithFrame_(self, frame):
        self.frame = frame
        return self
    def setDocumentView_(self, view) -> None:
        self.document_view = view
    def setHasVerticalScroller_(self, value) -> None:
        self.vertical_scroller = value
    def setHasHorizontalScroller_(self, value) -> None:
        self.horizontal_scroller = value
    def setAutohidesScrollers_(self, value) -> None:
        pass
    def contentView(self):
        return self
    def scrollToPoint_(self, point) -> None:
        self.scrolled_to = point
    def reflectScrolledClipView_(self, _view) -> None:
        pass


class FakePopUpButton(_FakeAlloc):
    def initWithFrame_pullsDown_(self, _frame, _pulls_down):
        self.selected = ""
        return self
    def addItemsWithTitles_(self, options) -> None:
        self.selected = options[0]
    def selectItemWithTitle_(self, option) -> None:
        self.selected = option
    def titleOfSelectedItem(self) -> str:
        return self.selected


class FakeTextField(_FakeAlloc):
    def initWithFrame_(self, _frame):
        self.value = ""
        return self
    def setStringValue_(self, value) -> None:
        self.value = value
    def stringValue(self) -> str:
        return self.value
    def setPlaceholderString_(self, _value) -> None:
        pass
    def setBezeled_(self, _value) -> None:
        pass
    def setDrawsBackground_(self, _value) -> None:
        pass
    def setEditable_(self, _value) -> None:
        pass
    def setSelectable_(self, _value) -> None:
        pass
    def setFont_(self, _value) -> None:
        pass

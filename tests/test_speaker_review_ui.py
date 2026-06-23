"""Tests for the speaker review UI flow."""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass, field
from pathlib import Path

from meeting_memory.types.transcript import SpeakerReviewState
from meeting_memory.ui.speaker_review import (
    FULL_TRANSCRIPT_RESPONSE,
    OPEN_MARKDOWN_RESPONSE,
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
    assert rumps.alerts[-1]["title"] == "Generate Notes"


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


def test_speaker_review_message_includes_longest_lines(tmp_path: Path) -> None:
    message = _review_message(_state(tmp_path))

    assert "Speaker A: Longest line: I can own the launch plan." in message
    assert "Speaker B: Longest line: I will update the deck." in message


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
        super().__init__(
            NSAlert=_FakeAlertFactory(responses),
            NSFont=types.SimpleNamespace(systemFontOfSize_=lambda _size: object()),
            NSMakeRect=lambda *args: args,
            NSPopUpButton=FakePopUpButton,
            NSTextField=FakeTextField,
            NSView=FakeView,
        )


class _FakeAlloc:
    @classmethod
    def alloc(cls):
        return cls()


class _FakeAlertFactory:
    def __init__(self, responses: list[int]) -> None:
        self.responses = responses

    def alloc(self):
        return FakeAlert(self.responses)


class FakeAlert:
    def __init__(self, responses: list[int]) -> None:
        self.responses = responses

    def init(self):
        return self

    def setMessageText_(self, _text) -> None:
        pass

    def setInformativeText_(self, _text) -> None:
        pass

    def addButtonWithTitle_(self, _title) -> None:
        pass

    def setAccessoryView_(self, _view) -> None:
        pass

    def runModal(self) -> int:
        return self.responses.pop(0)


class FakeView(_FakeAlloc):
    def initWithFrame_(self, _frame):
        return self

    def addSubview_(self, _view) -> None:
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

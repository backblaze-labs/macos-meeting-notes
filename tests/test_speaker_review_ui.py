"""Tests for the speaker review UI flow."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from meeting_memory.types.transcript import SpeakerReviewState
from meeting_memory.ui.speaker_review import (
    SpeakerReviewActions,
    _review_message,
    open_speaker_review_window,
)


def test_speaker_review_window_confirms_aliases_and_offers_notes(tmp_path: Path) -> None:
    rumps = FakeRumps(alert_responses=[1000, 1000])
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


def test_speaker_review_window_can_skip_notes_generation(tmp_path: Path) -> None:
    rumps = FakeRumps(alert_responses=[1001])
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
    assert actions.notes == []


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

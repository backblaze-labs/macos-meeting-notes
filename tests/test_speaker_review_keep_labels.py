"""Intentional speaker-label preservation through the review UI."""

from __future__ import annotations

from pathlib import Path

from meeting_memory.types.transcript import SpeakerReviewState
from meeting_memory.ui.speaker_review import (
    KEEP_SPEAKER_LABELS,
    SpeakerReviewActions,
    open_speaker_review_window,
)


def test_keep_labels_confirms_review_and_starts_notes(tmp_path: Path) -> None:
    kept: list[Path] = []
    notes: list[Path] = []

    def unexpected_alias_confirmation(_path: Path, _aliases: dict[str, str]) -> Path:
        raise AssertionError("aliases should not be confirmed")

    state = SpeakerReviewState(
        meeting_directory=tmp_path,
        transcript_path=tmp_path / "transcript.md",
        speaker_labels=("Speaker A", "Speaker B"),
        speaker_candidates=(),
        speaker_aliases={},
        speaker_status="needs_review",
        speaker_longest_lines={},
    )
    actions = SpeakerReviewActions(
        load_review=lambda _path: state,
        confirm_aliases=unexpected_alias_confirmation,
        keep_labels=lambda path: kept.append(path) or path / "transcript.md",
        generate_notes=notes.append,
    )

    opened = open_speaker_review_window(
        tmp_path,
        actions,
        rumps_module=object(),
        prompt_aliases=lambda _state: KEEP_SPEAKER_LABELS,
    )

    assert opened is True
    assert kept == [tmp_path]
    assert notes == [tmp_path]

"""Tests for local transcript relabeling and derived notes generation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from meeting_memory.service.frontmatter import replace_frontmatter
from meeting_memory.service.storage import read_frontmatter, write_meeting_dir
from meeting_memory.service.transcript_review import (
    confirm_speaker_aliases,
    generate_notes_from_transcript,
    list_speaker_review_meetings,
    load_speaker_review,
    relabel_transcript,
)
from meeting_memory.types.meeting import MeetingMeta
from meeting_memory.types.summary import ActionItem, SummaryResult
from meeting_memory.types.transcript import TranscriptResult, TranscriptSegment


def test_relabel_transcript_applies_yaml_aliases_without_llm(tmp_path: Path) -> None:
    files = _write_meeting(tmp_path)
    markdown = files.transcript_path.read_text(encoding="utf-8")
    frontmatter = read_frontmatter(files.transcript_path)
    frontmatter["speaker_aliases"] = {"Speaker A": "Alex", "Speaker B": "Casey"}
    files.transcript_path.write_text(replace_frontmatter(markdown, frontmatter), encoding="utf-8")

    relabel_transcript(files.directory)

    relabeled = files.transcript_path.read_text(encoding="utf-8")
    relabeled_frontmatter = read_frontmatter(files.transcript_path)
    assert relabeled_frontmatter["speaker_status"] == "confirmed"
    assert relabeled_frontmatter["participants"] == ["Alex", "Casey"]
    assert "**Participants:** Alex, Casey" in relabeled
    assert "**Alex** (0:00:05): Hello." in relabeled
    assert "**Casey** (0:00:08): Hi." in relabeled


def test_load_speaker_review_reads_candidates_and_labels(tmp_path: Path) -> None:
    files = _write_meeting(tmp_path)

    state = load_speaker_review(files.directory)

    assert state.meeting_directory == files.directory
    assert state.transcript_path == files.transcript_path
    assert state.speaker_labels == ("Speaker A", "Speaker B")
    assert state.speaker_candidates == ("Alex", "Casey")
    assert state.speaker_aliases == {}
    assert state.speaker_status == "needs_review"
    assert state.speaker_longest_lines == {
        "Speaker A": "This is the longer clue for identifying Alex.",
        "Speaker B": "Hi.",
    }


def test_load_speaker_review_accepts_assemblyai_letter_labels(tmp_path: Path) -> None:
    files = _write_meeting(tmp_path, speaker_labels=("A", "B"))

    state = load_speaker_review(files.directory)

    assert state.speaker_labels == ("A", "B")


def test_confirm_speaker_aliases_writes_frontmatter_and_relabels(tmp_path: Path) -> None:
    files = _write_meeting(tmp_path)

    confirm_speaker_aliases(
        files.directory,
        {"Speaker A": "Alex", "Speaker B": "Casey"},
    )

    relabeled = files.transcript_path.read_text(encoding="utf-8")
    frontmatter = read_frontmatter(files.transcript_path)
    assert frontmatter["speaker_aliases"] == {"Speaker A": "Alex", "Speaker B": "Casey"}
    assert frontmatter["speaker_status"] == "confirmed"
    assert "**Alex** (0:00:05): Hello." in relabeled
    assert "**Casey** (0:00:08): Hi." in relabeled


def test_confirm_speaker_aliases_requires_every_detected_label(tmp_path: Path) -> None:
    files = _write_meeting(tmp_path)

    with pytest.raises(ValueError, match="missing aliases for: Speaker B"):
        confirm_speaker_aliases(files.directory, {"Speaker A": "Alex"})


def test_list_speaker_review_meetings_skips_confirmed_transcripts(tmp_path: Path) -> None:
    files = _write_meeting(tmp_path)
    meetings_dir = files.directory.parent

    assert [meeting.slug for meeting in list_speaker_review_meetings(meetings_dir)] == [
        files.meta.slug
    ]

    confirm_speaker_aliases(
        files.directory,
        {"Speaker A": "Alex", "Speaker B": "Casey"},
    )

    assert list_speaker_review_meetings(meetings_dir) == []


def test_generate_notes_requires_confirmed_speakers(tmp_path: Path) -> None:
    files = _write_meeting(tmp_path)

    with pytest.raises(ValueError, match="speaker aliases must be confirmed"):
        generate_notes_from_transcript(files.directory, FakeSummarizer(_summary()))


def test_generate_notes_from_confirmed_transcript(tmp_path: Path) -> None:
    files = _write_meeting(tmp_path)
    markdown = files.transcript_path.read_text(encoding="utf-8")
    frontmatter = read_frontmatter(files.transcript_path)
    frontmatter["speaker_aliases"] = {"Speaker A": "Alex"}
    files.transcript_path.write_text(replace_frontmatter(markdown, frontmatter), encoding="utf-8")
    relabel_transcript(files.transcript_path)
    summarizer = FakeSummarizer(_summary())

    notes_path = generate_notes_from_transcript(files.directory, summarizer)

    notes = notes_path.read_text(encoding="utf-8")
    assert notes_path == files.directory / "notes.md"
    assert summarizer.transcript_text is not None
    assert "**Alex** (0:00:05): Hello." in summarizer.transcript_text
    assert "# Meeting Notes" in notes
    assert "## Summary" in notes
    assert "- [ ] Alex: Send update" in notes


@dataclass
class FakeSummarizer:
    result: SummaryResult
    transcript_text: str | None = None

    def summarize(self, transcript_text: str) -> SummaryResult:
        self.transcript_text = transcript_text
        return self.result


def _write_meeting(tmp_path: Path, *, speaker_labels: tuple[str, str] = ("Speaker A", "Speaker B")):
    audio = tmp_path / "recording.m4a"
    audio.write_bytes(b"audio")
    return write_meeting_dir(
        tmp_path / "meetings",
        MeetingMeta(
            slug="2026-06-18_10-00_sync",
            started_at=datetime(2026, 6, 18, 10, 0, tzinfo=UTC),
            calendar_title="Sync",
            duration_minutes=20,
            speaker_candidates=("Alex", "Casey"),
        ),
        audio,
        TranscriptResult(
            assemblyai_id="tx-123",
            segments=(
                TranscriptSegment(speaker_labels[0], 5, "Hello."),
                TranscriptSegment(speaker_labels[1], 8, "Hi."),
                TranscriptSegment(
                    speaker_labels[0],
                    12,
                    "This is the longer clue for identifying Alex.",
                ),
            ),
        ),
        SummaryResult.skipped(),
        speaker_candidates=("Alex", "Casey"),
    )


def _summary() -> SummaryResult:
    return SummaryResult(
        summary="Reviewed the sync.",
        decisions=("Keep transcript separate",),
        action_items=(ActionItem(owner="Alex", task="Send update"),),
    )

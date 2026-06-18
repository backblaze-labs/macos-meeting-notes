"""Tests for optional speaker mapping."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from meeting_memory.service.markdown import render_meeting_markdown
from meeting_memory.service.speaker_mapping import apply_speaker_mapping, load_speaker_mapping
from meeting_memory.types.meeting import MeetingMeta
from meeting_memory.types.summary import SummaryResult
from meeting_memory.types.transcript import TranscriptResult, TranscriptSegment


def test_load_speaker_mapping_from_json_file(tmp_path: Path) -> None:
    path = tmp_path / "speakers.json"
    path.write_text('{" Speaker A ": " Alex ", "Speaker B": "Alicia"}', encoding="utf-8")

    assert load_speaker_mapping(path) == {"Speaker A": "Alex", "Speaker B": "Alicia"}


def test_load_speaker_mapping_returns_empty_for_missing_optional_file(tmp_path: Path) -> None:
    assert load_speaker_mapping(None) == {}
    assert load_speaker_mapping(tmp_path / "missing.json") == {}


@pytest.mark.parametrize(
    "payload",
    [
        "[]",
        '{"Speaker A": ""}',
        '{"Speaker A": 1}',
    ],
)
def test_load_speaker_mapping_rejects_invalid_json_shape(tmp_path: Path, payload: str) -> None:
    path = tmp_path / "speakers.json"
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(ValueError):
        load_speaker_mapping(path)


def test_apply_speaker_mapping_replaces_known_labels_and_preserves_unknown() -> None:
    transcript = _transcript()

    mapped = apply_speaker_mapping(transcript, {"Speaker A": "Alex"})

    assert mapped.participants == ("Alex", "Speaker B")
    assert mapped.segments[0].speaker_label == "Alex"
    assert mapped.segments[1].speaker_label == "Speaker B"


def test_render_meeting_markdown_applies_speaker_mapping_to_participants_and_transcript() -> None:
    markdown = render_meeting_markdown(
        MeetingMeta(
            slug="2026-06-10_09-00_product-sync",
            started_at=datetime(2026, 6, 10, 9, 0, tzinfo=UTC),
            calendar_title="Product Sync",
            duration_minutes=12,
        ),
        _transcript(),
        SummaryResult(summary="A short summary."),
        speaker_mapping={"Speaker A": "Alex"},
    )

    assert 'participants: ["Alex", "Speaker B"]' in markdown
    assert "**Alex** (0:00:05): Hello." in markdown
    assert "**Speaker A**" not in markdown


def _transcript() -> TranscriptResult:
    return TranscriptResult(
        assemblyai_id="tx-123",
        segments=(
            TranscriptSegment("Speaker A", 5, "Hello."),
            TranscriptSegment("Speaker B", 12, "Hi."),
        ),
    )

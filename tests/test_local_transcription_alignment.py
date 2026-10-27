"""Alignment preserves text while assigning only supported anonymous labels."""

import pytest

from meeting_memory.service.local_transcription import align_local_transcript
from meeting_memory.types.local_transcription import (
    ASRSegment,
    ASRWord,
    DiarizationTurn,
    LocalTranscriptionOutput,
)


def output(segment, turns):
    return LocalTranscriptionOutput((segment,), tuple(turns), "es", 20)


def test_maximum_overlap_and_gaps_keep_all_words_and_punctuation():
    segment = ASRSegment(
        0,
        4,
        "Hola, equipo. ¿Todo bien?",
        (
            ASRWord("Hola,", 0, 0.4),
            ASRWord(" equipo.", 0.4, 1),
            ASRWord(" ¿Todo", 2, 2.6),
            ASRWord(" bien?", 3, 4),
        ),
    )
    result = align_local_transcript(
        output(
            segment,
            (
                DiarizationTurn(0, 1, "first"),
                DiarizationTurn(2.2, 2.8, "second"),
            ),
        )
    )
    assert [(part.speaker_label, part.text) for part in result.segments] == [
        ("Speaker A", "Hola, equipo."),
        ("Speaker B", "¿Todo"),
        ("Unknown", "bien?"),
    ]
    assert result.assemblyai_id is None
    assert " ".join(part.text for part in result.segments) == segment.text


def test_equal_overlap_uses_lexical_tie_and_zero_duration_is_half_open():
    segment = ASRSegment(
        0,
        4,
        "One two three",
        (
            ASRWord("One", 0.5, 1.5),
            ASRWord(" two", 1, 1),
            ASRWord(" three", 2, 2),
        ),
    )
    result = align_local_transcript(
        output(
            segment,
            (
                DiarizationTurn(1, 2, "b"),
                DiarizationTurn(0, 1, "a"),
            ),
        )
    )
    assert [part.speaker_label for part in result.segments] == ["Speaker A", "Speaker B", "Unknown"]


@pytest.mark.parametrize(
    "words", [(), (ASRWord("Missing", 0, 1),), (ASRWord("Preserve", None, None),)]
)
def test_absent_or_incomplete_word_timing_never_drops_segment_text(words):
    segment = ASRSegment(0, 2, "Preserve every token, please.", words)
    result = align_local_transcript(output(segment, (DiarizationTurn(0, 2, "a"),)))
    assert result.text == segment.text
    assert result.segments[0].speaker_label == "Unknown"


def test_invalid_and_nonfinite_timestamps_are_rejected():
    with pytest.raises(ValueError):
        ASRWord("word", float("nan"), 1)
    with pytest.raises(ValueError):
        DiarizationTurn(2, 1, "a")


def test_disjoint_turns_sum_overlap_per_speaker_before_selecting_label():
    segment = ASRSegment(0, 4, "word", (ASRWord("word", 0, 4),))
    result = align_local_transcript(
        output(
            segment,
            (
                DiarizationTurn(0, 1, "a"),
                DiarizationTurn(3, 4, "a"),
                DiarizationTurn(1, 2.5, "b"),
            ),
        )
    )
    assert result.segments[0].speaker_label == "Speaker A"


def test_equal_total_overlap_chooses_lexical_raw_id_even_when_it_starts_later():
    segment = ASRSegment(0, 2, "word", (ASRWord("word", 0, 2),))
    result = align_local_transcript(
        output(
            segment,
            (
                DiarizationTurn(0, 1, "b"),
                DiarizationTurn(1, 2, "a"),
            ),
        )
    )
    assert result.segments[0].speaker_label == "Speaker B"


def test_zero_duration_assignment_counts_containing_turns_per_raw_speaker():
    segment = ASRSegment(0, 3, "word", (ASRWord("word", 1, 1),))
    result = align_local_transcript(
        output(
            segment,
            (
                DiarizationTurn(0, 3, "a"),
                DiarizationTurn(0.1, 2, "b"),
                DiarizationTurn(0.5, 1.5, "b"),
            ),
        )
    )
    assert result.segments[0].speaker_label == "Speaker B"

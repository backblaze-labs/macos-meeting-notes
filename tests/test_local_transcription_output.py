"""Timestamped local output validation preserves ASR text and explicit gaps."""

from __future__ import annotations

import json

import pytest

from meeting_memory.repo.local_transcription import read_local_output
from meeting_memory.types.local_transcription import LocalTranscriptionError


def output(tmp_path, *, turn_end=2.0):
    row = {
        "segments": [
            {
                "start": 0.0,
                "end": 2.0,
                "text": " Hola, mundo.",
                "words": [
                    {"text": " Hola,", "start": 0.0, "end": 0.6},
                    {"text": " mundo.", "start": None, "end": None},
                ],
            }
        ],
        "turns": [{"start": 0.0, "end": turn_end, "speaker": "speaker_0"}],
        "language": "es",
    }
    path = tmp_path / "result.json"
    path.write_text(json.dumps(row))
    return path


def test_words_keep_original_spacing_punctuation_and_unavailable_timing(tmp_path):
    result = read_local_output(output(tmp_path), duration=2)
    assert result.language == "es"
    assert result.segments[0].text == " Hola, mundo."
    assert result.segments[0].words[1].start is None


@pytest.mark.parametrize("end", [float("nan"), float("inf"), -1, 100.0])
def test_invalid_timestamps_do_not_publish_a_transcript(tmp_path, end):
    with pytest.raises(LocalTranscriptionError):
        read_local_output(output(tmp_path, turn_end=end), duration=2)


def test_complete_diarization_failure_rejects_recognition_only_text(tmp_path):
    path = output(tmp_path)
    row = json.loads(path.read_text())
    row["turns"] = []
    path.write_text(json.dumps(row))
    with pytest.raises(LocalTranscriptionError):
        read_local_output(path, duration=2)


def test_output_symlink_is_not_followed(tmp_path):
    path = output(tmp_path)
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(LocalTranscriptionError):
        read_local_output(link, duration=2)


@pytest.mark.parametrize(
    "start,end",
    [
        (10.0, 11.0),
        (10.0, None),
        (None, 11.0),
        (float("nan"), None),
        (None, float("inf")),
        (-1.0, None),
    ],
)
def test_word_endpoints_cannot_escape_recording_or_be_nonfinite(tmp_path, start, end):
    path = output(tmp_path)
    row = json.loads(path.read_text())
    row["segments"][0]["end"] = 1.0
    row["segments"][0]["words"][0].update(start=start, end=end)
    path.write_text(json.dumps(row))
    with pytest.raises(LocalTranscriptionError):
        read_local_output(path, duration=2.0)

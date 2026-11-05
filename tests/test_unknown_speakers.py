"""Unknown fragments never establish a named identity."""

import pytest

from meeting_memory.service.speaker_state import reviewed_speaker_names
from meeting_memory.service.speaker_suggestions import validate_suggestions
from meeting_memory.types.speakers import (
    KnownSpeaker,
    SpeakerIdentificationRequest,
    SpeakerIdentificationResult,
    SpeakerSuggestion,
    SpeakerUtterance,
)


@pytest.mark.parametrize("label", ["Unknown", "unknown", "Speaker Unknown"])
def test_confirmation_preserves_unknown_even_with_alias(label):
    selected, aliases = reviewed_speaker_names(
        ("A", label),
        {"A": "Alex", label: "Casey"},
        False,
    )
    assert selected == {"A": "Alex", label: label}
    assert aliases == {"A": "Alex"}
    assert reviewed_speaker_names((label,), {}, False) == ({label: label}, {})


def test_unknown_direct_suggestion_is_rejected():
    request = SpeakerIdentificationRequest(
        (SpeakerUtterance("Unknown", "I am Alex"),),
        (KnownSpeaker("Alex"),),
    )
    result = SpeakerIdentificationResult((SpeakerSuggestion("Unknown", "Alex", "I am Alex"),))
    assert validate_suggestions(result, request) == ()


def test_native_review_has_no_unknown_assignment(monkeypatch, tmp_path):
    import sys
    from dataclasses import replace

    from speaker_review_fakes import FakeAppKit
    from test_speaker_review_ui import _state

    from meeting_memory.ui.speaker_review import _prompt_aliases_appkit
    from meeting_memory.ui.speaker_review_fields import _alias_text

    state = replace(_state(tmp_path), speaker_labels=("Speaker A", "Unknown"))
    appkit = FakeAppKit([1000])
    monkeypatch.setitem(sys.modules, "AppKit", appkit)
    aliases = _prompt_aliases_appkit(state, lambda path: None, lambda path: None)
    assert set(aliases) == {"Speaker A"}
    assert "Unknown=" not in _alias_text(state)


def test_saved_transcript_preserves_unknown_without_alias(tmp_path):
    from test_transcript_review import _write_meeting

    from meeting_memory.service.storage import read_frontmatter
    from meeting_memory.service.transcript_review import confirm_speaker_aliases

    files = _write_meeting(tmp_path, speaker_labels=("Speaker A", "Unknown"))
    confirm_speaker_aliases(files.directory, {"Speaker A": "Alex"})
    text = files.transcript_path.read_text()
    assert "**Unknown** (0:00:08): Hi." in text
    assert "**Alex** (0:00:05): Hello." in text
    metadata = read_frontmatter(files.transcript_path)
    assert metadata["speaker_status"] == "confirmed"
    assert metadata["speaker_aliases"] == {"Speaker A": "Alex"}

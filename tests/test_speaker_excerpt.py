"""Long-meeting context retains late speakers and exact chronological utterances."""

from meeting_memory.service.speaker_excerpt import MAX_SPEAKER_EXCERPT_CHARS, speaker_excerpt


def test_excerpt_includes_late_voice_after_long_dominant_speaker():
    opening = "\n".join(
        f"**A** (0:00:01): I review project {i}. " + "details " * 150 for i in range(60)
    )
    body = (
        opening
        + "\n**A** (0:30:00): Alex, your update?"
        "\n**B** (0:30:01): I am implementing the billing integration."
    )
    result = speaker_excerpt(body)
    assert any(turn.label == "B" for turn in result)
    assert result[-2].text == "Alex, your update?"
    assert result[-1].text == "I am implementing the billing integration."
    assert sum(len(t.label) + len(t.text) + 20 for t in result) <= MAX_SPEAKER_EXCERPT_CHARS


def test_excerpt_skips_oversized_turn_and_keeps_later_usable_voice():
    body = (
        "**A** (0:00:01): "
        + "x" * MAX_SPEAKER_EXCERPT_CHARS
        + "\n**B** (0:00:02): I maintain the SDK integration."
    )
    result = speaker_excerpt(body)
    assert len(result) == 1 and result[0].label == "B"

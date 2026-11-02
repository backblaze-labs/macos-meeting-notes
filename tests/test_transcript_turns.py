"""Rendered speaker turns preserve speech order, timestamps and document state."""

from datetime import UTC, datetime

import pytest

from meeting_memory.service.frontmatter import dump_frontmatter, split_frontmatter
from meeting_memory.service.markdown import render_transcript_markdown
from meeting_memory.service.meeting_state import MeetingStateStore
from meeting_memory.service.meeting_store import MeetingStore
from meeting_memory.service.storage import write_meeting_dir
from meeting_memory.service.transcript_review import confirm_speaker_aliases, relabel_transcript
from meeting_memory.service.transcript_state import TranscriptStateStore
from meeting_memory.service.transcript_turns import coalesce_transcript_turns
from meeting_memory.types.artifacts import MeetingJob
from meeting_memory.types.capabilities import MeetingJobState
from meeting_memory.types.meeting import MeetingMeta, PostCommitPolicy
from meeting_memory.types.summary import SummaryResult
from meeting_memory.types.transcript import TranscriptResult, TranscriptSegment

ALIASES = {"A": "Alex", "B": "Alex", "C": "Casey"}
EXPECTED = (
    "**Alex** (0:00:01): Hello world. Also.\n"
    "**Casey** (0:00:04): Interrupt.\n"
    "**Alex** (0:00:05): Return."
)


def transcript():
    return TranscriptResult(
        segments=(
            TranscriptSegment("A", 1, "Hello"),
            TranscriptSegment("A", 2, "world."),
            TranscriptSegment("B", 3, "Also."),
            TranscriptSegment("C", 4, "Interrupt."),
            TranscriptSegment("A", 5, "Return."),
        )
    )


def test_render_coalesces_displayed_names_without_mutating_source_segments():
    original = transcript()
    result = render_transcript_markdown(
        MeetingMeta("meeting", datetime(2026, 1, 1, tzinfo=UTC)),
        original,
        speaker_aliases=ALIASES,
    )
    assert EXPECTED in result
    assert [s.start_seconds for s in original.segments] == [1, 2, 3, 4, 5]
    assert [s.text for s in original.segments] == [
        "Hello",
        "world.",
        "Also.",
        "Interrupt.",
        "Return.",
    ]


def test_body_coalescing_preserves_sections_and_only_removes_internal_blank_spacing():
    original = (
        "# Transcript\n\n**Unknown** (0:00:01): First  text\n\n"
        "**Unknown** (0:00:02): second.\n\n## Interlude\n"
        "**Unknown** (0:00:03): Separate.\n"
        "**Other** (0:00:04): Interrupt.\n**Unknown** (0:00:05): Return.\n"
    )
    expected = original.replace(
        "First  text\n\n**Unknown** (0:00:02): second.", "First  text second."
    )
    assert coalesce_transcript_turns(original) == expected
    assert coalesce_transcript_turns(expected) == expected


def test_long_turn_is_not_split_and_newlines_in_asr_text_become_spacing():
    text = "word " * 20_000
    source = TranscriptResult(
        segments=(
            TranscriptSegment("A", 1, text),
            TranscriptSegment("A", 2, "next\nline"),
        )
    )
    result = render_transcript_markdown(MeetingMeta("meeting", datetime.now(UTC)), source)
    assert result.count("**A** (") == 1
    assert text + "next line" in result


@pytest.mark.parametrize("v2", [False, True])
@pytest.mark.parametrize("action", ["confirm", "relabel"])
def test_confirmation_and_relabel_merge_aliases_preserving_other_metadata(tmp_path, v2, action):
    audio = tmp_path / "source.m4a"
    audio.write_bytes(b"source audio")
    meta = MeetingMeta("meeting", datetime(2026, 1, 1, tzinfo=UTC))
    if v2:
        files = MeetingStore(tmp_path / "meetings").commit(
            audio, meta, PostCommitPolicy(transcription=True)
        )
        state = MeetingStateStore(files.directory.parent)
        state.transition_job(
            files.directory,
            MeetingJob.TRANSCRIPTION,
            MeetingJobState.PENDING,
            MeetingJobState.RUNNING,
        )
        TranscriptStateStore(files.directory.parent).succeed(files.directory, meta, transcript())
    else:
        files = write_meeting_dir(
            tmp_path / "meetings", meta, audio, transcript(), SummaryResult.skipped()
        )
    fields, body = split_frontmatter(files.transcript_path.read_text())
    fields["custom_field"] = {"preserve": "value"}
    if action == "relabel":
        fields["speaker_aliases"] = ALIASES
    body += "\n## Appendix\n**A** section note that is not transcript speech.\n"
    files.transcript_path.write_text(dump_frontmatter(fields) + "\n" + body)
    if action == "relabel":
        relabel_transcript(files.directory)
    else:
        confirm_speaker_aliases(files.directory, ALIASES)
    updated, body = split_frontmatter(files.transcript_path.read_text())
    assert EXPECTED in body
    assert "## Appendix\n**A** section note that is not transcript speech." in body
    for key, value in fields.items():
        if key not in {"participants", "speaker_aliases", "speaker_status"}:
            assert updated[key] == value
    before = files.transcript_path.read_text()
    relabel_transcript(files.directory)
    assert files.transcript_path.read_text() == before
    if v2:
        # Terminal aliases stay intact when repairing historical display fragmentation.
        fields, body = split_frontmatter(before)
        body = body.replace("Hello world. Also.", "Hello\n**Alex** (0:00:02): world. Also.")
        files.transcript_path.write_text(dump_frontmatter(fields) + "\n" + body)
        relabel_transcript(files.directory)
        final_fields, final_body = split_frontmatter(files.transcript_path.read_text())
        assert EXPECTED in final_body
        assert final_fields == fields

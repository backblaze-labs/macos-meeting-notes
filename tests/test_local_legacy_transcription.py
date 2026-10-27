"""Explicit legacy retries use local attempts without remote sentinel IDs."""

from datetime import UTC, datetime

from meeting_memory.service.frontmatter import split_frontmatter
from meeting_memory.service.local_transcription import LocalTranscriptAdapter
from meeting_memory.service.processing_retry import retry_failed_processing
from meeting_memory.service.runtime_notes import generate_owned_notes
from meeting_memory.service.storage import write_meeting_dir
from meeting_memory.service.transcript_review import confirm_speaker_aliases, load_speaker_review
from meeting_memory.types.events import TranscriptionProgress, TranscriptReady
from meeting_memory.types.local_transcription import (
    ASRSegment,
    ASRWord,
    DiarizationTurn,
    LocalModelProgress,
    LocalTranscriptionOutput,
)
from meeting_memory.types.meeting import MeetingMeta
from meeting_memory.types.summary import SummaryResult
from meeting_memory.types.transcript import TranscriptResult


def test_legacy_local_retry_claims_before_call_and_preserves_review_notes(tmp_path):
    source = tmp_path / "source.m4a"
    source.write_bytes(b"private audio")
    files = write_meeting_dir(
        tmp_path / "meetings",
        MeetingMeta("legacy", datetime(2026, 10, 27, tzinfo=UTC)),
        source,
        TranscriptResult("transcription-failed", (), error="old failure"),
        SummaryResult.skipped(),
    )
    events = []

    class Backend:
        def transcribe(self, audio, *, progress, cancelled):
            fields, _ = split_frontmatter(files.transcript_path.read_text())
            assert fields["transcription_provider"] == "local"
            assert fields["transcription_status"] == "running"
            assert fields["assemblyai_id"] is None
            assert len(fields["transcription_attempt_id"]) == 32
            assert audio.read() == b"private audio"
            progress(LocalModelProgress("transcribing", "Transcribing locally."))
            return LocalTranscriptionOutput(
                (ASRSegment(0, 1, "Hola.", (ASRWord("Hola.", 0, 1),)),),
                (DiarizationTurn(0, 1, "a"),),
                "es",
                1,
            )

    result = retry_failed_processing(
        files.directory.parent, LocalTranscriptAdapter(Backend()), event_sink=events.append
    )
    assert result.completed == 1
    assert result.failed == 0
    state = load_speaker_review(files.transcript_path)
    assert state.assemblyai_id is None
    assert state.transcription_provider == "local"
    assert state.speaker_labels == ("Speaker A",)
    assert any(isinstance(event, TranscriptionProgress) for event in events)
    assert any(isinstance(event, TranscriptReady) for event in events)
    confirm_speaker_aliases(files.transcript_path, {}, keep_labels=True)

    class Summarizer:
        def summarize(self, text):
            assert "Hola." in text
            return SummaryResult("Local transcript, optional external notes.")

    notes = generate_owned_notes(files.directory.parent, files.directory, Summarizer())
    assert notes.is_file()
    assert files.audio_path.read_bytes() == b"private audio"

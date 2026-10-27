"""Remote job resume verifies its durable source fingerprint across restart."""

from datetime import UTC, datetime

import pytest

from meeting_memory.service.frontmatter import merge_frontmatter_fields
from meeting_memory.service.meeting_state import MeetingStateConflict
from meeting_memory.service.meeting_store import MeetingStore
from meeting_memory.service.runtime_files import bind_runtime_meeting_files
from meeting_memory.service.transcript_state import TranscriptStateStore
from meeting_memory.service.transcription_attempts import claim_attempt
from meeting_memory.types.meeting import MeetingMeta, PostCommitPolicy
from meeting_memory.types.transcription import TranscriptionProvider


def submitted(tmp_path):
    audio = tmp_path / "source.m4a"
    audio.write_bytes(b"original source")
    files = MeetingStore(tmp_path / "meetings").commit(
        audio,
        MeetingMeta("resume", datetime(2026, 10, 27, tzinfo=UTC)),
        PostCommitPolicy(transcription=True),
    )
    handle = bind_runtime_meeting_files(files.directory.parent, files)
    attempt = claim_attempt(files.directory.parent, handle, TranscriptionProvider.ASSEMBLYAI)
    TranscriptStateStore(files.directory.parent).record_job_id(
        files.directory, "remote-job", expected_attempt=attempt
    )
    return files, handle, attempt


def test_unchanged_remote_resume_preserves_attempt_and_source_identity(tmp_path):
    files, handle, original = submitted(tmp_path)
    resumed = claim_attempt(
        files.directory.parent, handle, TranscriptionProvider.ASSEMBLYAI, resume_id="remote-job"
    )
    assert resumed == original


def test_changed_source_cannot_be_bound_to_old_remote_job_after_restart(tmp_path):
    files, handle, original = submitted(tmp_path)
    files.audio_path.write_bytes(b"changed source")
    before = files.transcript_path.read_bytes()
    with pytest.raises(MeetingStateConflict, match="submitted remote job"):
        claim_attempt(
            files.directory.parent, handle, TranscriptionProvider.ASSEMBLYAI, resume_id="remote-job"
        )
    assert files.transcript_path.read_bytes() == before


def test_legacy_running_remote_job_can_be_adopted_only_when_remote_selected(tmp_path):
    files, handle, original = submitted(tmp_path)
    text = merge_frontmatter_fields(
        files.transcript_path.read_text(),
        {
            "transcription_provider": None,
            "transcription_attempt_id": None,
            "transcription_audio_sha256": None,
            "transcription_audio_size": None,
        },
    )
    files.transcript_path.write_text(text)
    with pytest.raises(MeetingStateConflict):
        claim_attempt(
            files.directory.parent, handle, TranscriptionProvider.LOCAL, resume_id="remote-job"
        )
    resumed = claim_attempt(
        files.directory.parent, handle, TranscriptionProvider.ASSEMBLYAI, resume_id="remote-job"
    )
    assert resumed.attempt_id != original.attempt_id


def test_changed_remote_source_explains_failure_then_allows_separate_fresh_retry(tmp_path):
    from test_runtime_jobs import ImmediateThread

    from meeting_memory.service.frontmatter import split_frontmatter
    from meeting_memory.service.runtime_jobs import RuntimeJobs
    from meeting_memory.service.runtime_retry import retry_v2_transcriptions
    from meeting_memory.types.events import TranscriptionFailed, TranscriptReady
    from meeting_memory.types.transcript import TranscriptResult, TranscriptSegment

    files, handle, original = submitted(tmp_path)
    files.audio_path.write_bytes(b"current saved recording")
    events, calls = [], []

    class Cloud:
        def submit(self, audio):
            calls.append("submit")
            assert audio.read() == b"current saved recording"
            return "fresh-job"

        def resume(self, identifier):
            calls.append("resume")
            assert identifier == "fresh-job"
            return TranscriptResult(identifier, (TranscriptSegment("A", 0, "Current recording."),))

    jobs = RuntimeJobs(
        files.directory.parent,
        events.append,
        transcription_client=Cloud(),
        thread_factory=ImmediateThread,
    )
    assert retry_v2_transcriptions(files.directory.parent, jobs) == 1
    fields, _ = split_frontmatter(files.transcript_path.read_text())
    assert fields["transcription_status"] == "failed"
    assert fields["transcription_attempt_id"] == original.attempt_id
    assert calls == []
    assert isinstance(events[-1], TranscriptionFailed)
    assert "Recording changed" in events[-1].summary
    assert "Retry again" in events[-1].action
    assert retry_v2_transcriptions(files.directory.parent, jobs) == 1
    assert calls == ["submit", "resume"]
    assert isinstance(events[-1], TranscriptReady)
    assert retry_v2_transcriptions(files.directory.parent, jobs) == 0

"""Local runtime never resumes cloud jobs and seals each source and attempt."""

from datetime import UTC, datetime

import pytest

from meeting_memory.service.frontmatter import split_frontmatter
from meeting_memory.service.meeting_state import MeetingStateConflict
from meeting_memory.service.meeting_store import MeetingStore
from meeting_memory.service.runtime_files import bind_runtime_meeting_files
from meeting_memory.service.runtime_jobs import RuntimeJobs
from meeting_memory.service.runtime_retry import retry_v2_transcriptions
from meeting_memory.service.transcript_state import TranscriptStateStore
from meeting_memory.service.transcription_attempts import claim_attempt
from meeting_memory.types.events import TranscriptionFailed, TranscriptReady
from meeting_memory.types.local_transcription import (
    ASRSegment,
    ASRWord,
    DiarizationTurn,
    LocalModelsUnavailable,
    LocalTranscriptionError,
    LocalTranscriptionOutput,
)
from meeting_memory.types.meeting import MeetingMeta, PostCommitPolicy
from meeting_memory.types.transcription import TranscriptionProvider


class ImmediateThread:
    def __init__(self, target, args=(), **kwargs):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


def meeting(tmp_path):
    source = tmp_path / "source.m4a"
    source.write_bytes(b"private source")
    return MeetingStore(tmp_path / "meetings").commit(
        source,
        MeetingMeta("local-meeting", datetime(2026, 10, 27, tzinfo=UTC)),
        PostCommitPolicy(transcription=True),
    )


def output():
    return LocalTranscriptionOutput(
        (ASRSegment(0, 1, "Hola.", (ASRWord("Hola.", 0, 1),)),),
        (DiarizationTurn(0, 1, "speaker0"),),
        "es",
        1,
    )


def metadata(files):
    return split_frontmatter(files.transcript_path.read_text())[0]


class LocalClient:
    def __init__(self, files, error=None, mutate=None):
        self.files, self.error, self.mutate, self.calls = files, error, mutate, 0

    def transcribe(self, audio, **kwargs):
        state = metadata(self.files)
        assert state["transcription_provider"] == "local"
        assert state["transcription_status"] == "running"
        assert len(state["transcription_attempt_id"]) == 32
        assert state["assemblyai_id"] is None
        assert audio.read() == b"private source"
        self.calls += 1
        if self.mutate:
            self.mutate()
        if self.error:
            raise self.error
        return output()

    def submit(self, audio):
        raise AssertionError("Local called cloud submit")

    def resume(self, job):
        raise AssertionError("Local called cloud resume")


def jobs(files, client, events, **kwargs):
    return RuntimeJobs(
        files.directory.parent,
        events.append,
        transcription_client=client,
        transcription_provider=TranscriptionProvider.LOCAL,
        thread_factory=ImmediateThread,
        **kwargs,
    )


def test_local_success_preserves_audio_and_uses_no_cloud_id(tmp_path):
    files, events = meeting(tmp_path), []
    client = LocalClient(files)
    jobs(files, client, events).launch_for_commit(files, transcription=True, backup=False)
    state = metadata(files)
    assert client.calls == 1
    assert state["transcription_status"] == "succeeded"
    assert state["assemblyai_id"] is None
    assert state["speaker_status"] == "needs_review"
    assert files.audio_path.read_bytes() == b"private source"
    assert any(isinstance(event, TranscriptReady) for event in events)


def test_local_explicit_retry_never_resumes_inherited_remote_id(tmp_path):
    from meeting_memory.service.frontmatter import merge_frontmatter_fields

    files, events = meeting(tmp_path), []
    files.transcript_path.write_text(
        merge_frontmatter_fields(
            files.transcript_path.read_text(),
            {
                "transcription_status": "running",
                "assemblyai_id": "inherited-remote-id",
            },
        )
    )
    client = LocalClient(files)
    assert retry_v2_transcriptions(files.directory.parent, jobs(files, client, events)) == 1
    assert metadata(files)["transcription_status"] == "succeeded"
    assert client.calls == 1


@pytest.mark.parametrize(
    "error,state",
    [
        (LocalModelsUnavailable("Models are not ready.", "Prepare Local Models."), "pending"),
        (LocalTranscriptionError("Diarization failed.", "Retry local transcription."), "failed"),
    ],
)
def test_local_unavailability_or_failure_never_publishes_partial_results(tmp_path, error, state):
    files, events = meeting(tmp_path), []
    jobs(files, LocalClient(files, error=error), events).launch_for_commit(
        files, transcription=True, backup=False
    )
    assert metadata(files)["transcription_status"] == state
    assert files.audio_path.read_bytes() == b"private source"
    assert any(isinstance(event, TranscriptionFailed) for event in events)
    assert not any(isinstance(event, TranscriptReady) for event in events)
    assert not (files.directory / "notes.md").exists()


def test_changed_audio_rejects_completion_and_never_offers_review(tmp_path):
    files, events = meeting(tmp_path), []
    client = LocalClient(files, mutate=lambda: files.audio_path.write_bytes(b"replacement"))
    jobs(files, client, events).launch_for_commit(files, transcription=True, backup=False)
    assert metadata(files)["transcription_status"] == "running"
    assert not any(isinstance(event, TranscriptReady) for event in events)


def test_old_attempt_cannot_complete_after_explicit_retry(tmp_path):
    from dataclasses import replace

    from meeting_memory.service.local_transcription import align_local_transcript

    files = meeting(tmp_path)
    handle = bind_runtime_meeting_files(files.directory.parent, files)
    old = claim_attempt(files.directory.parent, handle, TranscriptionProvider.LOCAL)
    store = TranscriptStateStore(files.directory.parent)
    store.prepare_retry(files.directory, expected_directory_identity=handle.directory_identity)
    current = claim_attempt(files.directory.parent, handle, TranscriptionProvider.LOCAL)
    before = files.transcript_path.read_bytes()
    result = align_local_transcript(output(), attempt_id=old.attempt_id)
    with pytest.raises(MeetingStateConflict):
        store.succeed(files.directory, files.meta, result, expected_attempt=old)
    assert files.transcript_path.read_bytes() == before
    store.succeed(
        files.directory,
        files.meta,
        replace(result, attempt_id=current.attempt_id),
        expected_attempt=current,
    )
    assert metadata(files)["transcription_status"] == "succeeded"


def test_local_transcript_reconciles_prior_backup_and_preserves_review_notes(tmp_path):
    from meeting_memory.service.backup_revision import capture_backup_snapshot
    from meeting_memory.service.meeting_state import MeetingStateStore
    from meeting_memory.service.runtime_notes import generate_owned_notes
    from meeting_memory.service.transcript_review import (
        confirm_speaker_aliases,
        load_speaker_review,
    )
    from meeting_memory.types.artifacts import MeetingJob
    from meeting_memory.types.capabilities import MeetingJobState
    from meeting_memory.types.summary import SummaryResult

    files, events = meeting(tmp_path), []
    store = MeetingStateStore(files.directory.parent)
    store.transition_job(
        files.directory, MeetingJob.BACKUP, MeetingJobState.NOT_REQUESTED, MeetingJobState.PENDING
    )
    store.transition_job(
        files.directory, MeetingJob.BACKUP, MeetingJobState.PENDING, MeetingJobState.RUNNING
    )
    with capture_backup_snapshot(files.directory) as snapshot:
        revision = snapshot.revision
    store.complete_backup(
        files.directory,
        revision,
        f"meetings/{files.meta.slug}/recording.m4a",
        f"meetings/{files.meta.slug}/transcript.md",
    )
    jobs(files, LocalClient(files), events).launch_for_commit(
        files, transcription=True, backup=False
    )
    state = metadata(files)
    assert state["backup_status"] == "pending"
    assert state["backup_uploaded_revision"] == revision
    review = load_speaker_review(files.directory)
    assert review.transcription_provider == "local"
    assert review.transcription_attempt_id == state["transcription_attempt_id"]
    confirm_speaker_aliases(files.directory, {"Speaker A": "Reviewed Person"})

    class Summarizer:
        def summarize(self, text):
            assert "Reviewed Person" in text
            return SummaryResult("Summary of reviewed local transcript.")

    assert generate_owned_notes(files.directory.parent, files.directory, Summarizer()).is_file()
    assert metadata(files)["transcription_attempt_id"] == state["transcription_attempt_id"]


def test_pausing_local_after_inference_leaves_explicitly_retryable_pending_state(tmp_path):
    files, events = meeting(tmp_path), []
    enabled = [True]
    client = LocalClient(files, mutate=lambda: enabled.__setitem__(0, False))
    runtime = jobs(files, client, events, capability_enabled=lambda _cap: enabled[0])
    runtime.launch_for_commit(files, transcription=True, backup=False)
    assert metadata(files)["transcription_status"] == "pending"
    assert not any(isinstance(event, TranscriptReady) for event in events)


def test_shutdown_cancels_active_local_work_and_closes_client_once(tmp_path):
    from meeting_memory.types.local_transcription import LocalTranscriptionCancelled

    files, events = meeting(tmp_path), []
    closed = []
    runtime = None

    class ClosingClient(LocalClient):
        def close(self):
            closed.append(True)

        def transcribe(self, audio, *, cancelled, progress):
            runtime.shutdown()
            assert cancelled()
            raise LocalTranscriptionCancelled()

    client = ClosingClient(files)
    runtime = jobs(files, client, events)
    runtime.launch_for_commit(files, transcription=True, backup=False)
    runtime.shutdown()
    assert closed == [True]
    assert metadata(files)["transcription_status"] == "pending"
    assert not runtime.transcription_enabled
    assert not any(isinstance(event, TranscriptReady) for event in events)

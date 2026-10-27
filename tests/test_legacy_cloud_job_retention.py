"""Legacy cloud retries persist their exact job before polling or pausing."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from transcription_fakes import FakeAssemblyAI

from meeting_memory.repo import transcription
from meeting_memory.repo.transcription import AssemblyAITranscriptionClient
from meeting_memory.service.frontmatter import split_frontmatter
from meeting_memory.service.processing_retry import retry_failed_processing
from meeting_memory.service.storage import write_meeting_dir
from meeting_memory.types.events import TranscriptReady
from meeting_memory.types.meeting import MeetingMeta
from meeting_memory.types.summary import SummaryResult
from meeting_memory.types.transcript import TranscriptResult


class Clock:
    now = 0

    def __call__(self):
        return self.now

    def sleep(self, delay):
        self.now += delay


def stored(tmp_path):
    source = tmp_path / "source.m4a"
    source.write_bytes(b"private audio")
    return write_meeting_dir(
        tmp_path / "meetings",
        MeetingMeta("legacy-cloud", datetime(2026, 10, 27, tzinfo=UTC)),
        source,
        TranscriptResult("transcription-failed", (), error="old failure"),
        SummaryResult.skipped(),
    )


def response(status="completed"):
    return SimpleNamespace(
        id="remote-job",
        status=status,
        utterances=(SimpleNamespace(speaker="A", start=0, text="Ready."),),
    )


def fields(files):
    return split_frontmatter(files.transcript_path.read_text())[0]


@pytest.mark.parametrize(
    "failure,state", [("pause", "pending"), ("failure", "failed"), ("deadline", "failed")]
)
def test_failed_or_paused_cloud_job_keeps_id_and_next_retry_only_resumes(
    tmp_path,
    monkeypatch,
    failure,
    state,
):
    files, clock, admitted, events = stored(tmp_path), Clock(), [True], []
    fake = FakeAssemblyAI(response())
    if failure == "pause":
        fake.on_create = lambda: admitted.__setitem__(0, False)
    elif failure == "failure":
        fake.polls = [TimeoutError("temporary poll failure")]
    else:
        fake.response = response("processing")
    original_poll = fake.api.get_transcript

    def poll(http, identifier):
        before = fields(files)
        assert before["assemblyai_id"] == identifier == "remote-job"
        assert before["transcription_provider"] == "assemblyai"
        assert before["transcription_status"] == "running"
        return original_poll(http, identifier)

    fake.api.get_transcript = poll
    monkeypatch.setattr(transcription, "_load_assemblyai", lambda: fake)
    adapter = AssemblyAITranscriptionClient(
        "key",
        external_processing_accepted=True,
        clock=clock,
        sleeper=clock.sleep,
        admit_request=lambda: admitted[0],
        timeout_seconds=5,
        poll_interval_seconds=3,
        retry_delays=(),
    )
    first = retry_failed_processing(files.directory.parent, adapter, event_sink=events.append)
    previous = fields(files)
    assert first.completed == 0
    assert previous["transcription_status"] == state
    assert previous["assemblyai_id"] == "remote-job"
    assert len(fake.created_urls) == 1
    if failure == "pause":
        assert fake.resumed_ids == []
    assert not any(isinstance(event, TranscriptReady) for event in events)
    admitted[0] = True
    fake.response = response()
    second = retry_failed_processing(files.directory.parent, adapter, event_sink=events.append)
    current = fields(files)
    assert second.completed == 1
    assert current["assemblyai_id"] == "remote-job"
    assert current["transcription_attempt_id"] == previous["transcription_attempt_id"]
    assert len(fake.created_urls) == 1
    assert files.audio_path.read_bytes() == b"private audio"
    assert retry_failed_processing(files.directory.parent, adapter).attempted == 0


def test_create_id_arriving_at_deadline_is_persisted_before_resume(tmp_path, monkeypatch):
    files, clock = stored(tmp_path), Clock()
    fake = FakeAssemblyAI(response(), on_create=lambda: setattr(clock, "now", 5))
    original_poll = fake.api.get_transcript

    def poll(http, identifier):
        assert fields(files)["assemblyai_id"] == identifier == "remote-job"
        return original_poll(http, identifier)

    fake.api.get_transcript = poll
    monkeypatch.setattr(transcription, "_load_assemblyai", lambda: fake)
    adapter = AssemblyAITranscriptionClient(
        "key",
        external_processing_accepted=True,
        clock=clock,
        sleeper=clock.sleep,
        timeout_seconds=5,
    )
    result = retry_failed_processing(files.directory.parent, adapter)
    assert result.completed == 1
    assert fields(files)["assemblyai_id"] == "remote-job"
    assert len(fake.created_urls) == 1
    assert fake.resumed_ids == ["remote-job"]

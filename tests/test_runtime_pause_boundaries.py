"""Provider admission and durable-state behavior at live-disable boundaries."""

from __future__ import annotations

from test_runtime_jobs import BackupClient, ImmediateThread, TranscriptionClient, _meeting

from meeting_memory.service.frontmatter import split_frontmatter
from meeting_memory.service.runtime_jobs import RuntimeJobs
from meeting_memory.service.runtime_transcription import RuntimeTranscription
from meeting_memory.types.capabilities import Capability
from meeting_memory.types.egress import EgressPaused


class SequenceGate:
    def __init__(self, allowed_calls: int) -> None:
        self.allowed_calls = allowed_calls
        self.calls = 0

    def __call__(self, _capability: Capability | None = None) -> bool:
        self.calls += 1
        return self.calls <= self.allowed_calls


def test_pause_after_transcription_claim_defers_to_pending_without_submit(tmp_path) -> None:
    files = _meeting(tmp_path)
    gate = SequenceGate(2)
    client = TranscriptionClient(files.transcript_path)
    runtime = RuntimeTranscription(
        files.directory.parent,
        lambda _event: None,
        client,
        ImmediateThread,
        enabled=gate,
    )

    runtime.start(files)

    frontmatter, _body = split_frontmatter(files.transcript_path.read_text(encoding="utf-8"))
    assert client.calls == []
    assert frontmatter["transcription_status"] == "pending"
    assert frontmatter.get("assemblyai_id") is None


def test_pause_after_submit_keeps_running_job_id_for_resume_without_resubmit(
    tmp_path,
) -> None:
    files = _meeting(tmp_path)
    gate = SequenceGate(3)
    client = TranscriptionClient(files.transcript_path)
    runtime = RuntimeTranscription(
        files.directory.parent,
        lambda _event: None,
        client,
        ImmediateThread,
        enabled=gate,
    )

    runtime.start(files)

    frontmatter, _body = split_frontmatter(files.transcript_path.read_text(encoding="utf-8"))
    assert client.calls == [("submit", b"audio")]
    assert frontmatter["transcription_status"] == "running"
    assert frontmatter["assemblyai_id"] == "job-1"


def test_pause_after_backup_claim_defers_to_pending_without_upload(tmp_path) -> None:
    files = _meeting(tmp_path)
    gate = SequenceGate(2)
    client = BackupClient()
    jobs = RuntimeJobs(
        files.directory.parent,
        lambda _event: None,
        backup_client=client,
        thread_factory=ImmediateThread,
        capability_enabled=gate,
    )

    jobs.launch_for_commit(files, transcription=False, backup=True)

    frontmatter, _body = split_frontmatter(files.transcript_path.read_text(encoding="utf-8"))
    assert client.calls == []
    assert frontmatter["backup_status"] == "pending"


def test_typed_backup_pause_defers_without_failed_state(tmp_path) -> None:
    files = _meeting(tmp_path)

    class PausedBackup(BackupClient):
        def upload_backup_snapshot(self, _request, *, cancellation):
            cancellation.cancel()
            raise EgressPaused("paused")

    jobs = RuntimeJobs(
        files.directory.parent,
        lambda _event: None,
        backup_client=PausedBackup(),
        thread_factory=ImmediateThread,
    )

    jobs.launch_for_commit(files, transcription=False, backup=True)

    frontmatter, _body = split_frontmatter(files.transcript_path.read_text(encoding="utf-8"))
    assert frontmatter["backup_status"] == "pending"

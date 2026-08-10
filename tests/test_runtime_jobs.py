import io
from datetime import UTC, datetime
from pathlib import Path

from meeting_memory.service.frontmatter import split_frontmatter
from meeting_memory.service.meeting_state import MeetingStateStore
from meeting_memory.service.meeting_store import MeetingStore
from meeting_memory.service.runtime_jobs import RuntimeJobs
from meeting_memory.service.transcript_state import TranscriptStateStore
from meeting_memory.types.artifacts import (
    ArtifactFieldOwner,
    BackupSnapshotUploadResult,
    BackupUploadDisposition,
    MeetingJob,
)
from meeting_memory.types.capabilities import MeetingJobState
from meeting_memory.types.events import TranscriptReady
from meeting_memory.types.meeting import MeetingMeta, PostCommitPolicy
from meeting_memory.types.transcript import TranscriptResult, TranscriptSegment


class ImmediateThread:
    def __init__(self, target, args=(), **_kwargs) -> None:
        self.target = target
        self.args = args

    def start(self) -> None:
        self.target(*self.args)


class DeferredThread(ImmediateThread):
    created = []

    def __init__(self, target, args=(), **kwargs) -> None:
        super().__init__(target, args, **kwargs)
        self.started = False
        self.__class__.created.append(self)

    def start(self) -> None:
        self.started = True

    def run(self) -> None:
        self.target(*self.args)


class TranscriptionClient:
    def __init__(self, transcript_path: Path) -> None:
        self.transcript_path = transcript_path
        self.calls: list[object] = []

    def submit(self, audio: io.BufferedIOBase) -> str:
        self.calls.append(("submit", audio.read()))
        return "job-1"

    def resume(self, job_id: str) -> TranscriptResult:
        frontmatter, _ = split_frontmatter(self.transcript_path.read_text(encoding="utf-8"))
        assert frontmatter["assemblyai_id"] == job_id
        self.calls.append(("resume", job_id))
        return TranscriptResult(job_id, (TranscriptSegment("A", 0, "Hello"),))


class BackupClient:
    def __init__(self, disposition=BackupUploadDisposition.COMPLETE) -> None:
        self.disposition = disposition
        self.calls = []

    def upload_backup_snapshot(self, request, *, cancellation):
        self.calls.append((request, cancellation))
        audio_key = f"meetings/{request.meeting_slug}/recording.m4a"
        return BackupSnapshotUploadResult(
            self.disposition,
            request.meeting_slug,
            request.revision,
            audio_key=(
                audio_key
                if self.disposition is not BackupUploadDisposition.CANCELLED
                else None
            ),
            transcript_key=(
                f"meetings/{request.meeting_slug}/transcript.md"
                if self.disposition is BackupUploadDisposition.COMPLETE
                else None
            ),
        )


def _meeting(tmp_path: Path):
    audio = tmp_path / "source.m4a"
    audio.write_bytes(b"audio")
    meta = MeetingMeta(
        "2026-08-10_10-00_sync",
        datetime(2026, 8, 10, 10, tzinfo=UTC),
        "Sync",
    )
    files = MeetingStore(tmp_path / "meetings").commit(
        audio,
        meta,
        PostCommitPolicy(transcription=True, backup=True),
    )
    return files


def test_runtime_jobs_persist_id_before_poll_and_finish_independently(
    tmp_path: Path,
) -> None:
    files = _meeting(tmp_path)
    transcript = TranscriptionClient(files.transcript_path)
    backup = BackupClient()
    events: list[object] = []
    jobs = RuntimeJobs(
        files.directory.parent,
        events.append,
        transcription_client=transcript,
        backup_client=backup,
        thread_factory=ImmediateThread,
    )

    jobs.launch_for_commit(files, transcription=True, backup=True)

    frontmatter, body = split_frontmatter(files.transcript_path.read_text(encoding="utf-8"))
    assert transcript.calls == [("submit", b"audio"), ("resume", "job-1")]
    assert len(backup.calls) == 1
    assert frontmatter["transcription_status"] == "succeeded"
    assert frontmatter["backup_status"] == "succeeded"
    assert frontmatter["assemblyai_id"] == "job-1"
    assert "**A**" in body
    assert events == [TranscriptReady(events[0].meeting)]


def test_transcription_path_swap_during_submit_cannot_change_uploaded_bytes(
    tmp_path: Path,
) -> None:
    files = _meeting(tmp_path)
    secret = tmp_path / "secret"
    secret.write_bytes(b"outside-secret")

    class SwappingClient(TranscriptionClient):
        def submit(self, audio: io.BufferedIOBase) -> str:
            files.audio_path.unlink()
            files.audio_path.symlink_to(secret)
            self.calls.append(("submit", audio.read()))
            return "job-1"

    client = SwappingClient(files.transcript_path)
    jobs = RuntimeJobs(
        files.directory.parent,
        lambda _event: None,
        transcription_client=client,
        thread_factory=ImmediateThread,
    )

    jobs.launch_for_commit(files, transcription=True, backup=False)

    assert client.calls[0] == ("submit", b"audio")
    assert secret.read_bytes() == b"outside-secret"


def test_partial_backup_returns_to_pending_without_keys(tmp_path: Path) -> None:
    files = _meeting(tmp_path)
    backup = BackupClient(BackupUploadDisposition.PARTIAL)
    jobs = RuntimeJobs(
        files.directory.parent,
        lambda _event: None,
        backup_client=backup,
        thread_factory=ImmediateThread,
    )

    jobs.launch_for_commit(files, transcription=False, backup=True)

    frontmatter, _ = split_frontmatter(files.transcript_path.read_text(encoding="utf-8"))
    assert frontmatter["backup_status"] == "pending"
    assert frontmatter.get("b2_audio") is None
    assert frontmatter.get("b2_transcript") is None


def test_disabling_backup_does_not_scan_or_launch_historical_work(tmp_path: Path) -> None:
    files = _meeting(tmp_path)
    backup = BackupClient()
    jobs = RuntimeJobs(
        files.directory.parent,
        lambda _event: None,
        backup_client=backup,
        thread_factory=ImmediateThread,
    )

    jobs.set_backup_enabled(False)
    jobs.launch_for_commit(files, transcription=False, backup=True)

    frontmatter, _ = split_frontmatter(files.transcript_path.read_text(encoding="utf-8"))
    assert backup.calls == []
    assert frontmatter["backup_status"] == "pending"


def test_two_concurrent_resume_requests_poll_provider_once(tmp_path: Path) -> None:
    DeferredThread.created = []
    files = _meeting(tmp_path)
    state = MeetingStateStore(files.directory.parent)
    state.transition_job(
        files.directory,
        MeetingJob.TRANSCRIPTION,
        MeetingJobState.PENDING,
        MeetingJobState.RUNNING,
    )
    TranscriptStateStore(files.directory.parent).record_job_id(files.directory, "job-1")
    transcript = TranscriptionClient(files.transcript_path)
    jobs = RuntimeJobs(
        files.directory.parent,
        lambda _event: None,
        transcription_client=transcript,
        thread_factory=DeferredThread,
    )

    jobs.retry_transcription(files, resume_id="job-1")
    jobs.retry_transcription(files, resume_id="job-1")

    assert len(DeferredThread.created) == 1
    DeferredThread.created[0].run()
    assert transcript.calls == [("resume", "job-1")]


def test_failed_retry_replaces_old_job_id_before_new_provider_resume(tmp_path: Path) -> None:
    files = _meeting(tmp_path)
    state = MeetingStateStore(files.directory.parent)
    state.transition_job(
        files.directory,
        MeetingJob.TRANSCRIPTION,
        MeetingJobState.PENDING,
        MeetingJobState.RUNNING,
    )
    transcripts = TranscriptStateStore(files.directory.parent)
    transcripts.record_job_id(files.directory, "job-old")
    transcripts.fail(files.directory, "job-old")
    client = TranscriptionClient(files.transcript_path)
    jobs = RuntimeJobs(
        files.directory.parent,
        lambda _event: None,
        transcription_client=client,
        thread_factory=ImmediateThread,
    )

    jobs.retry_transcription(files)

    frontmatter, _ = split_frontmatter(files.transcript_path.read_text(encoding="utf-8"))
    assert client.calls == [("submit", b"audio"), ("resume", "job-1")]
    assert frontmatter["assemblyai_id"] == "job-1"
    assert frontmatter["transcription_status"] == "succeeded"


def test_backup_revision_change_releases_token_and_relaunches_once(tmp_path: Path) -> None:
    files = _meeting(tmp_path)
    state = MeetingStateStore(files.directory.parent)

    class MutatingBackupClient(BackupClient):
        def upload_backup_snapshot(self, request, *, cancellation):
            if not self.calls:
                state.merge_fields(
                    files.directory,
                    ArtifactFieldOwner.SPEAKERS,
                    {"speaker_candidates": ["Ada"]},
                )
            return super().upload_backup_snapshot(request, cancellation=cancellation)

    backup = MutatingBackupClient()
    jobs = RuntimeJobs(
        files.directory.parent,
        lambda _event: None,
        backup_client=backup,
        thread_factory=ImmediateThread,
    )

    jobs.launch_for_commit(files, transcription=False, backup=True)

    frontmatter, _ = split_frontmatter(files.transcript_path.read_text(encoding="utf-8"))
    assert len(backup.calls) == 2
    assert backup.calls[0][0].revision != backup.calls[1][0].revision
    assert frontmatter["backup_status"] == "succeeded"
    assert frontmatter["backup_uploaded_revision"] == backup.calls[1][0].revision

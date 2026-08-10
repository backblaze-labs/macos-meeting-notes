"""Adversarial identity checks at optional runtime job boundaries."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from meeting_memory.service.frontmatter import split_frontmatter
from meeting_memory.service.local_commit import LocalRecordingCommitter
from meeting_memory.service.meeting_state import MeetingStateStore
from meeting_memory.service.meeting_store import MeetingStore
from meeting_memory.service.recovery_index import create_recovery_session, pin_recovery_source
from meeting_memory.service.runtime_jobs import RuntimeJobs
from meeting_memory.service.runtime_retry import (
    retry_v2_backups,
    retry_v2_transcriptions,
)
from meeting_memory.service.transcript_state import TranscriptStateStore
from meeting_memory.types.artifacts import MeetingJob
from meeting_memory.types.capabilities import MeetingJobState
from meeting_memory.types.events import RecordingCommitted
from meeting_memory.types.meeting import MeetingFiles, MeetingMeta, PostCommitPolicy


class ImmediateThread:
    def __init__(self, target, args=(), **_kwargs) -> None:
        self.target = target
        self.args = args

    def start(self) -> None:
        self.target(*self.args)


class RecordingTranscriber:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def submit(self, _audio) -> str:
        self.calls.append("submit")
        return "job"

    def resume(self, _job_id):
        self.calls.append("resume")
        raise AssertionError("forged files reached Transcription")


class RecordingBackup:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def upload_backup_snapshot(self, _request, *, cancellation):
        self.calls.append("upload")
        raise AssertionError("forged files reached Backup")


class SwappingThread:
    created: list[SwappingThread] = []

    def __init__(self, target, args=(), **_kwargs) -> None:
        self.target = target
        self.args = args
        self.clone_before = b""
        self.__class__.created.append(self)

    def start(self) -> None:
        meeting_dir = self.args[0].files.directory
        clone = meeting_dir.with_name(f"{meeting_dir.name}.clone")
        detached = meeting_dir.with_name(f"{meeting_dir.name}.detached")
        shutil.copytree(meeting_dir, clone)
        (clone / "recording.m4a").write_bytes(b"REPLACEMENT_SECRET")
        meeting_dir.rename(detached)
        clone.rename(meeting_dir)
        self.clone_before = (meeting_dir / "transcript.md").read_bytes()

    def run(self) -> None:
        self.target(*self.args)


def test_forged_meta_for_another_owned_directory_never_reaches_providers(
    tmp_path: Path,
) -> None:
    source = tmp_path / "audio.m4a"
    source.write_bytes(b"private audio")
    stored_meta = MeetingMeta(
        "meeting-b",
        datetime(2026, 8, 10, 10, tzinfo=UTC),
        "Meeting B",
    )
    stored = MeetingStore(tmp_path / "meetings").commit(
        source,
        stored_meta,
        PostCommitPolicy(transcription=True, backup=True),
    )
    forged = MeetingFiles(
        MeetingMeta("meeting-a", stored_meta.started_at, stored_meta.calendar_title),
        stored.directory,
        stored.audio_path,
        stored.transcript_path,
    )
    transcription = RecordingTranscriber()
    backup = RecordingBackup()
    jobs = RuntimeJobs(
        stored.directory.parent,
        lambda _event: None,
        transcription_client=transcription,
        backup_client=backup,
        thread_factory=ImmediateThread,
    )

    jobs.launch_for_commit(forged, transcription=True, backup=True)
    jobs.retry_transcription(forged)
    jobs.retry_backup(forged)

    frontmatter, _ = split_frontmatter(stored.transcript_path.read_text(encoding="utf-8"))
    assert transcription.calls == []
    assert backup.calls == []
    assert frontmatter["transcription_status"] == "pending"
    assert frontmatter["backup_status"] == "pending"


@pytest.mark.parametrize("job", ["transcription", "backup"])
@pytest.mark.parametrize("retry", [False, True], ids=["start", "retry"])
def test_directory_clone_swap_before_worker_never_egresses_or_mutates_clone(
    tmp_path: Path,
    job: str,
    retry: bool,
) -> None:
    SwappingThread.created = []
    source = tmp_path / "audio.m4a"
    source.write_bytes(b"ORIGINAL_AUDIO")
    meta = MeetingMeta(
        "owned-meeting",
        datetime(2026, 8, 10, 10, tzinfo=UTC),
        "Owned Meeting",
    )
    files = MeetingStore(tmp_path / "meetings").commit(
        source,
        meta,
        PostCommitPolicy(transcription=True, backup=True),
    )
    if retry:
        _make_failed(files, job)
    transcription = RecordingTranscriber()
    backup = RecordingBackup()
    events: list[object] = []
    jobs = RuntimeJobs(
        files.directory.parent,
        events.append,
        transcription_client=transcription,
        backup_client=backup,
        thread_factory=SwappingThread,
    )

    if retry and job == "transcription":
        assert retry_v2_transcriptions(files.directory.parent, jobs) == 1
    elif retry:
        assert retry_v2_backups(files.directory.parent, jobs) == 1
    else:
        jobs.launch_for_commit(
            files,
            transcription=job == "transcription",
            backup=job == "backup",
        )

    assert len(SwappingThread.created) == 1
    worker = SwappingThread.created[0]
    worker.run()
    assert transcription.calls == []
    assert backup.calls == []
    assert events == []
    assert files.audio_path.read_bytes() == b"REPLACEMENT_SECRET"
    assert files.transcript_path.read_bytes() == worker.clone_before


def _make_failed(files: MeetingFiles, job: str) -> None:
    state = MeetingStateStore(files.directory.parent)
    selected = MeetingJob.TRANSCRIPTION if job == "transcription" else MeetingJob.BACKUP
    state.transition_job(
        files.directory,
        selected,
        MeetingJobState.PENDING,
        MeetingJobState.RUNNING,
    )
    if selected is MeetingJob.TRANSCRIPTION:
        TranscriptStateStore(files.directory.parent).fail(files.directory)
    else:
        state.transition_job(
            files.directory,
            MeetingJob.BACKUP,
            MeetingJobState.RUNNING,
            MeetingJobState.FAILED,
        )


def test_commit_sealed_identity_rejects_clone_swapped_by_event(
    tmp_path: Path,
) -> None:
    meta = MeetingMeta(
        "event-swap",
        datetime(2026, 8, 10, 10, tzinfo=UTC),
        "Event Swap",
    )
    entry = create_recovery_session(tmp_path / "capture", meta)
    entry.source_path.write_bytes(b"RIFF\x00\x00\x00\x00WAVEsamples")
    entry = pin_recovery_source(entry)
    meetings = tmp_path / "meetings-event-swap"
    transcription = RecordingTranscriber()
    backup = RecordingBackup()
    clone_before: list[bytes] = []
    jobs = RuntimeJobs(
        meetings,
        lambda _event: None,
        transcription_client=transcription,
        backup_client=backup,
        thread_factory=ImmediateThread,
    )

    def swap_on_commit(event: object) -> None:
        if not isinstance(event, RecordingCommitted):
            return
        original = event.meeting.directory
        clone = original.with_name(f"{original.name}.clone")
        shutil.copytree(original, clone)
        (clone / "recording.m4a").write_bytes(b"REPLACEMENT_SECRET")
        original.rename(original.with_name(f"{original.name}.detached"))
        clone.rename(original)
        clone_before.append((original / "transcript.md").read_bytes())

    committer = LocalRecordingCommitter(
        MeetingStore(meetings),
        swap_on_commit,
        converter=lambda _wav, output: output.write_bytes(b"VALID"),
        validate_m4a=lambda _path: None,
        policy_provider=lambda: PostCommitPolicy(True, True),
        post_commit_launcher=lambda files, policy: jobs.launch_for_commit(
            files,
            transcription=policy.transcription,
            backup=policy.backup,
        ),
    )

    files = committer.commit(entry, meta)

    assert files is not None
    assert transcription.calls == []
    assert backup.calls == []
    assert files.audio_path.read_bytes() == b"REPLACEMENT_SECRET"
    assert files.transcript_path.read_bytes() == clone_before[0]

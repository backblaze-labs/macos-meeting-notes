from datetime import UTC, datetime
from pathlib import Path

from meeting_memory.service.meeting_state import MeetingStateStore
from meeting_memory.service.meeting_store import MeetingStore
from meeting_memory.service.runtime_retry import (
    retry_v2_backups,
    retry_v2_transcriptions,
)
from meeting_memory.service.transcript_state import TranscriptStateStore
from meeting_memory.types.artifacts import MeetingJob
from meeting_memory.types.capabilities import MeetingJobState
from meeting_memory.types.meeting import MeetingMeta, PostCommitPolicy


class Jobs:
    def __init__(self) -> None:
        self.transcription = []
        self.backup = []

    def retry_transcription(self, files, *, resume_id=None) -> None:
        self.transcription.append((files, resume_id))

    def retry_backup(self, files) -> None:
        self.backup.append(files)


def _meeting(tmp_path: Path):
    audio = tmp_path / "source.m4a"
    audio.write_bytes(b"audio")
    return MeetingStore(tmp_path / "meetings").commit(
        audio,
        MeetingMeta(
            "2026-08-10_10-00_sync",
            datetime(2026, 8, 10, 10, tzinfo=UTC),
            "Sync",
        ),
        PostCommitPolicy(transcription=True, backup=True),
    )


def test_explicit_retry_scans_owned_v2_without_legacy_writers(
    tmp_path: Path,
    monkeypatch,
) -> None:
    files = _meeting(tmp_path)
    legacy = files.directory.parent / "legacy"
    legacy.mkdir()
    (legacy / "recording.m4a").write_bytes(b"legacy")
    (legacy / "transcript.md").write_text(
        "---\nid: legacy\ndate: 2026-08-10T10:00:00+00:00\n"
        "assemblyai_id: old\n---\nlegacy\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "meeting_memory.service.storage.write_transcript_markdown",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("legacy writer")),
    )
    monkeypatch.setattr(
        "meeting_memory.service.storage.update_b2_frontmatter",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("legacy writer")),
    )
    jobs = Jobs()

    assert retry_v2_transcriptions(files.directory.parent, jobs) == 1

    assert [item[0].files.meta.slug for item in jobs.transcription] == [files.meta.slug]
    assert jobs.backup == []


def test_explicit_retry_resumes_exact_running_provider_job(tmp_path: Path) -> None:
    files = _meeting(tmp_path)
    state = MeetingStateStore(files.directory.parent)
    state.transition_job(
        files.directory,
        MeetingJob.TRANSCRIPTION,
        MeetingJobState.PENDING,
        MeetingJobState.RUNNING,
    )
    TranscriptStateStore(files.directory.parent).record_job_id(files.directory, "job-7")
    jobs = Jobs()

    retry_v2_transcriptions(files.directory.parent, jobs)

    assert [(item.files.meta.slug, job_id) for item, job_id in jobs.transcription] == [
        (files.meta.slug, "job-7")
    ]


def test_backup_only_retry_does_not_schedule_transcription(tmp_path: Path) -> None:
    files = _meeting(tmp_path)
    jobs = Jobs()

    assert retry_v2_backups(files.directory.parent, jobs) == 1
    assert jobs.transcription == []
    assert len(jobs.backup) == 1

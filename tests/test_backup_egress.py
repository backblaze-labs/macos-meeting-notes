"""Backup egress boundaries for automatic post-transcription and review uploads.

Automatic Backup work is limited to the meeting that just changed. Historical
meetings stay queued until the user invokes the explicit retry action, per
`docs/local-first-contract.md`.
"""

from __future__ import annotations

import queue
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from meeting_memory.config.runtime import RuntimeSettings
from meeting_memory.service.frontmatter import split_frontmatter
from meeting_memory.service.meeting_state import MeetingStateStore
from meeting_memory.service.meeting_store import MeetingStore
from meeting_memory.service.runtime_backup_gate import RuntimeBackupGate
from meeting_memory.service.runtime_jobs import RuntimeJobs
from meeting_memory.service.runtime_retry import retry_v2_backup
from meeting_memory.types.artifacts import (
    BackupSnapshotUploadResult,
    BackupUploadDisposition,
    MeetingJob,
)
from meeting_memory.types.capabilities import MeetingJobState
from meeting_memory.types.meeting import MeetingMeta, PostCommitPolicy
from meeting_memory.types.transcript import TranscriptResult, TranscriptSegment
from meeting_memory.ui import controller as controller_module
from meeting_memory.ui import runtime_app
from meeting_memory.ui.controller import TrayController


class ImmediateThread:
    def __init__(self, target, args=(), **_kwargs) -> None:
        self.target = target
        self.args = args

    def start(self) -> None:
        self.target(*self.args)


class TranscriptionClient:
    def __init__(self, transcript_path: Path) -> None:
        self.transcript_path = transcript_path

    def submit(self, audio) -> str:
        audio.read()
        return "job-1"

    def resume(self, job_id: str) -> TranscriptResult:
        return TranscriptResult(job_id, (TranscriptSegment("A", 0, "Hello"),))


class BackupClient:
    def __init__(self) -> None:
        self.uploads: list[str] = []

    def upload_backup_snapshot(self, request, *, cancellation):
        self.uploads.append(request.meeting_slug)
        return BackupSnapshotUploadResult(
            BackupUploadDisposition.COMPLETE,
            request.meeting_slug,
            request.revision,
            audio_key=f"meetings/{request.meeting_slug}/recording.m4a",
            transcript_key=f"meetings/{request.meeting_slug}/transcript.md",
        )


def _commit(meetings_dir: Path, tmp_path: Path, slug: str):
    audio = tmp_path / f"{slug}.m4a"
    audio.write_bytes(b"audio")
    meta = MeetingMeta(slug, datetime(2026, 8, 10, 10, tzinfo=UTC), "Sync")
    return MeetingStore(meetings_dir).commit(
        audio,
        meta,
        PostCommitPolicy(transcription=True, backup=True),
    )


def _backup_status(transcript_path: Path) -> str:
    frontmatter, _ = split_frontmatter(transcript_path.read_text(encoding="utf-8"))
    return str(frontmatter["backup_status"])


def test_finished_transcription_uploads_the_rewritten_transcript(tmp_path: Path) -> None:
    meetings_dir = tmp_path / "meetings"
    files = _commit(meetings_dir, tmp_path, "2026-08-10_10-00_sync")
    backup = BackupClient()
    jobs = RuntimeJobs(
        meetings_dir,
        lambda _event: None,
        transcription_client=TranscriptionClient(files.transcript_path),
        backup_client=backup,
        thread_factory=ImmediateThread,
    )

    jobs.launch_for_commit(files, transcription=False, backup=True)
    assert backup.uploads == ["2026-08-10_10-00_sync"]
    assert _backup_status(files.transcript_path) == "succeeded"

    jobs.launch_for_commit(files, transcription=True, backup=False)

    assert backup.uploads == ["2026-08-10_10-00_sync"] * 2
    assert _backup_status(files.transcript_path) == "succeeded"


def test_speaker_review_backs_up_only_the_reviewed_meeting(
    tmp_path: Path,
    monkeypatch,
) -> None:
    reviewed: list[Path] = []
    backlog_scans: list[object] = []
    controller = TrayController(
        settings=SimpleNamespace(max_recording_minutes=180),
        recorder=type("Recorder", (), {"temp_dir": tmp_path})(),
        event_queue=queue.Queue(),
        sync_runner=lambda: backlog_scans.append("scan"),
        backup_runner=reviewed.append,
    )
    transcript = tmp_path / "transcript.md"
    monkeypatch.setattr(
        controller_module,
        "confirm_speaker_aliases",
        lambda path, aliases, *, keep_labels=False: path,
    )

    result = controller.confirm_speaker_aliases(transcript, {"A": "Alex"})

    assert result == transcript
    assert reviewed == [transcript]
    assert backlog_scans == []


def test_app_launch_never_uploads_the_backup_backlog(tmp_path: Path, monkeypatch) -> None:
    meetings_dir = tmp_path / "meetings"
    files = _commit(meetings_dir, tmp_path, "2026-08-10_10-00_backlog")
    settings = RuntimeSettings(
        meetings_dir=meetings_dir,
        b2_application_key_id="id",
        b2_application_key="key",
        b2_endpoint="https://s3.example.invalid",
        b2_region="region",
        b2_bucket_name="bucket",
    )
    backlog_retries: list[object] = []

    class Tray:
        controller = None

        def __init__(self, controller, *, readiness_report, configuration_surface=None) -> None:
            type(self).controller = controller

        def run(self) -> None:
            return None

    monkeypatch.setattr(
        runtime_app,
        "load_configuration",
        lambda _use: SimpleNamespace(
            settings=settings,
            meetings_dir_path=settings.meetings_dir_path,
            transcription=settings.transcription,
            backup=settings.backup,
            calendar=settings.calendar,
            notes=settings.notes,
        ),
    )
    monkeypatch.setattr(runtime_app, "RumpsTrayApp", Tray)
    monkeypatch.setattr(runtime_app, "B2S3Client", lambda *_a, **_k: BackupClient())
    monkeypatch.setattr(
        runtime_app,
        "_retry_backups",
        lambda *args, **kwargs: backlog_retries.append(args),
    )

    assert runtime_app.run_runtime_app() == 0

    assert backlog_retries == []
    assert _backup_status(files.transcript_path) == "pending"
    assert Tray.controller.sync_runner is not None


def test_backup_gate_queues_a_request_refused_during_an_active_upload() -> None:
    gate = RuntimeBackupGate(True, lambda: True)
    token = gate.register("2026-08-10_10-00_sync")

    assert token is not None
    assert gate.register("2026-08-10_10-00_sync") is None
    assert gate.release("2026-08-10_10-00_sync", token) is True

    second = gate.register("2026-08-10_10-00_sync")
    assert second is not None
    assert gate.release("2026-08-10_10-00_sync", second) is False


def test_abandoned_claim_leaves_the_queued_followup_for_the_next_release() -> None:
    gate = RuntimeBackupGate(True, lambda: True)
    token = gate.register("2026-08-10_10-00_sync")
    assert gate.register("2026-08-10_10-00_sync") is None

    gate.abandon("2026-08-10_10-00_sync", token)
    later = gate.register("2026-08-10_10-00_sync")

    assert later is not None
    assert gate.release("2026-08-10_10-00_sync", later) is True


def test_automatic_per_meeting_backup_never_resets_a_running_upload(tmp_path: Path) -> None:
    meetings_dir = tmp_path / "meetings"
    files = _commit(meetings_dir, tmp_path, "2026-08-10_10-00_running")
    MeetingStateStore(meetings_dir).transition_job(
        files.directory,
        MeetingJob.BACKUP,
        MeetingJobState.PENDING,
        MeetingJobState.RUNNING,
    )
    backup = BackupClient()
    jobs = RuntimeJobs(
        meetings_dir,
        lambda _event: None,
        backup_client=backup,
        thread_factory=ImmediateThread,
    )

    assert retry_v2_backup(meetings_dir, jobs, files.directory) is False
    assert backup.uploads == []
    assert _backup_status(files.transcript_path) == "running"

"""Local-first runtime composition for the macOS tray app."""

from __future__ import annotations

import logging
import queue
import sys
import tempfile
from pathlib import Path

from pydantic import ValidationError

from meeting_memory.config.runtime import RuntimeSettings, load_runtime_settings
from meeting_memory.config.settings import format_settings_error
from meeting_memory.logging_config import configure_logging
from meeting_memory.repo.b2_client import B2S3Client
from meeting_memory.repo.calendar_client import GoogleCalendarClient
from meeting_memory.repo.native_audio import convert_native_audio
from meeting_memory.repo.native_audio_validation import validate_native_m4a
from meeting_memory.repo.summarizer import ClaudeSummarizer
from meeting_memory.repo.transcription import AssemblyAITranscriptionClient
from meeting_memory.service.calendar_watcher import CalendarWatcher
from meeting_memory.service.local_commit import LocalRecordingCommitter
from meeting_memory.service.meeting_store import MeetingStore
from meeting_memory.service.processing_retry import retry_failed_processing
from meeting_memory.service.recorder import RecorderService
from meeting_memory.service.runtime_jobs import RuntimeJobs
from meeting_memory.service.runtime_legacy_recovery import LegacyRecoveryRuntime
from meeting_memory.service.runtime_notes import generate_owned_notes
from meeting_memory.service.runtime_retry import (
    retry_v2_backups,
    retry_v2_transcriptions,
)
from meeting_memory.service.sync import sync_pending_meetings
from meeting_memory.types.meeting import PostCommitPolicy
from meeting_memory.ui.controller import TrayController
from meeting_memory.ui.setup_tray import RumpsSetupApp
from meeting_memory.ui.tray import RumpsTrayApp

LOGGER = logging.getLogger(__name__)


def run_runtime_app() -> int:
    try:
        settings = load_runtime_settings()
    except ValidationError as exc:
        sys.stderr.write(format_settings_error(exc))
        return _run_setup_app()

    configure_logging()
    event_queue: queue.Queue[object] = queue.Queue()
    transcription_client = _transcription_client(settings)
    backup_client = _backup_client(settings)
    jobs = RuntimeJobs(
        settings.meetings_dir_path,
        event_queue.put,
        transcription_client=transcription_client,
        backup_client=backup_client,
    )
    committer = LocalRecordingCommitter(
        MeetingStore(settings.meetings_dir_path),
        event_queue.put,
        convert_native_audio,
        validate_native_m4a,
        policy_provider=lambda: PostCommitPolicy(
            transcription=transcription_client is not None,
            backup=jobs.backup_enabled,
        ),
        post_commit_launcher=lambda files, policy: jobs.launch_for_commit(
            files,
            transcription=policy.transcription,
            backup=policy.backup,
        ),
    )
    recorder = RecorderService(temp_dir=_recording_staging(settings))
    legacy_recovery = LegacyRecoveryRuntime(
        Path(tempfile.gettempdir()),
        _legacy_recovery_marker(settings),
        committer,
        event_queue.put,
    )
    controller = TrayController(
        settings=settings,
        recorder=recorder,
        committer=committer,
        event_queue=event_queue,
        sync_runner=(
            lambda: _retry_backups(settings, jobs, backup_client)
        ),
        processing_retry_runner=lambda: _retry_transcriptions(
            settings,
            jobs,
            transcription_client,
        ),
        notes_generator=_notes_generator(settings),
        legacy_recovery=legacy_recovery,
    )
    watcher = _calendar_watcher(settings, event_queue)
    if watcher is not None:
        try:
            watcher.start()
        except Exception:
            LOGGER.warning("Calendar watcher could not start")
    RumpsTrayApp(controller, readiness_report=None).run()
    return 0


def _transcription_client(
    settings: RuntimeSettings,
) -> AssemblyAITranscriptionClient | None:
    config = settings.transcription
    if config is None:
        return None
    try:
        return AssemblyAITranscriptionClient(config.api_key)
    except Exception:
        LOGGER.warning("Transcription capability could not start")
        return None


def _backup_client(settings: RuntimeSettings) -> B2S3Client | None:
    config = settings.backup
    if config is None:
        return None
    try:
        return B2S3Client(
            config.application_key_id,
            config.application_key,
            config.endpoint,
            config.region,
            config.bucket_name,
        )
    except Exception:
        LOGGER.warning("Backup capability could not start")
        return None


def _notes_generator(settings: RuntimeSettings):
    config = settings.notes
    if config is None:
        return None
    try:
        summarizer = ClaudeSummarizer(
            api_key=config.api_key,
            model=config.model,
            prompt_file=config.prompt_file,
        )
    except Exception:
        LOGGER.warning("Notes capability could not start")
        return None

    def generate(path):
        meeting_dir = path if path.is_dir() else path.parent
        return generate_owned_notes(settings.meetings_dir_path, meeting_dir, summarizer)

    return generate


def _calendar_watcher(
    settings: RuntimeSettings,
    event_queue: queue.Queue[object],
) -> CalendarWatcher | None:
    config = settings.calendar
    if config is None or not config.credentials_file.is_file():
        return None
    try:
        client = GoogleCalendarClient(
            credentials_file=config.credentials_file,
            calendar_id=config.calendar_id,
            known_speakers=settings.known_speakers,
        )
        return CalendarWatcher(
            client=client,
            event_sink=event_queue.put,
            notify_minutes_before=config.notify_minutes_before,
            poll_interval_seconds=config.poll_interval,
        )
    except Exception:
        LOGGER.warning("Calendar capability could not start")
        return None


def _recording_staging(settings: RuntimeSettings):
    return settings.meetings_dir_path / ".meeting-memory-staging" / "recordings"


def _legacy_recovery_marker(settings: RuntimeSettings):
    return (
        settings.meetings_dir_path
        / ".meeting-memory-staging"
        / "legacy-recovery"
        / "legacy-recovery-scan.json"
    )


def _retry_transcriptions(settings, jobs, client) -> None:
    if client is None:
        return
    retry_v2_transcriptions(settings.meetings_dir_path, jobs)
    retry_failed_processing(settings.meetings_dir_path, client)


def _retry_backups(settings, jobs, client) -> None:
    if client is None:
        return
    retry_v2_backups(settings.meetings_dir_path, jobs)
    sync_pending_meetings(settings.meetings_dir_path, client)


def _run_setup_app() -> int:
    configure_logging()
    RumpsSetupApp(readiness_report=None).run()
    return 0

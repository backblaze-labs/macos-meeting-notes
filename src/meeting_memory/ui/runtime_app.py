"""Local-first runtime composition for the macOS tray app."""

from __future__ import annotations

import logging
import queue
import tempfile
from pathlib import Path

from meeting_memory.config.runtime import RuntimeSettings
from meeting_memory.logging_config import configure_logging
from meeting_memory.repo.b2_client import B2S3Client
from meeting_memory.repo.calendar_client import GoogleCalendarClient
from meeting_memory.repo.native_audio import convert_native_audio
from meeting_memory.repo.native_audio_validation import validate_native_m4a
from meeting_memory.repo.summarizer import ClaudeSummarizer
from meeting_memory.repo.transcription import AssemblyAITranscriptionClient
from meeting_memory.service.calendar_watcher import CalendarWatcher
from meeting_memory.service.configuration_loader import (
    ConfigurationLoadError,
    LoadedConfiguration,
    load_configuration,
)
from meeting_memory.service.configuration_surface import ConfigurationSurfaceCoordinator
from meeting_memory.service.local_commit import LocalRecordingCommitter
from meeting_memory.service.meeting_store import MeetingStore
from meeting_memory.service.processing_retry import retry_failed_processing
from meeting_memory.service.recorder import RecorderService
from meeting_memory.service.runtime_capabilities import RuntimeCapabilityPause
from meeting_memory.service.runtime_jobs import RuntimeJobs
from meeting_memory.service.runtime_legacy_recovery import LegacyRecoveryRuntime
from meeting_memory.service.runtime_notes import generate_owned_notes
from meeting_memory.service.runtime_retry import (
    retry_v2_backups,
    retry_v2_transcriptions,
)
from meeting_memory.service.sync import sync_pending_meetings
from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration_resolution import ConfigurationUse
from meeting_memory.types.meeting import PostCommitPolicy
from meeting_memory.ui.controller import TrayController
from meeting_memory.ui.setup_tray import RumpsSetupApp
from meeting_memory.ui.tray import RumpsTrayApp

LOGGER = logging.getLogger(__name__)


def run_runtime_app() -> int:
    try:
        configuration = load_configuration(ConfigurationUse.RUNTIME)
    except ConfigurationLoadError:
        return _run_setup_app()

    settings = configuration.settings
    configure_logging()
    event_queue: queue.Queue[object] = queue.Queue()
    runtime_capabilities = RuntimeCapabilityPause()
    transcription_client = _transcription_client(
        configuration,
        enabled=lambda: runtime_capabilities.allows(Capability.TRANSCRIPTION),
    )
    backup_client = _backup_client(
        configuration,
        enabled=lambda: runtime_capabilities.allows(Capability.BACKUP),
    )
    jobs = RuntimeJobs(
        settings.meetings_dir_path,
        event_queue.put,
        transcription_client=transcription_client,
        backup_client=backup_client,
        capability_enabled=runtime_capabilities.allows,
    )
    committer = LocalRecordingCommitter(
        MeetingStore(settings.meetings_dir_path),
        event_queue.put,
        convert_native_audio,
        validate_native_m4a,
        policy_provider=lambda: PostCommitPolicy(
            transcription=jobs.transcription_enabled,
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
        sync_runner=(lambda: _retry_backups(settings, jobs, backup_client)),
        processing_retry_runner=lambda: _retry_transcriptions(
            settings,
            jobs,
            transcription_client,
        ),
        notes_generator=_notes_generator(
            configuration,
            enabled=lambda: runtime_capabilities.allows(Capability.NOTES),
        ),
        notes_allowed=lambda: runtime_capabilities.allows(Capability.NOTES),
        legacy_recovery=legacy_recovery,
    )
    watcher = _calendar_watcher(
        configuration,
        event_queue,
        enabled=lambda: runtime_capabilities.allows(Capability.CALENDAR),
    )
    runtime_capabilities.register(
        Capability.TRANSCRIPTION,
        lambda: jobs.set_transcription_enabled(False),
    )
    runtime_capabilities.register(
        Capability.BACKUP,
        lambda: jobs.set_backup_enabled(False),
    )
    runtime_capabilities.register(
        Capability.NOTES,
        lambda: controller.set_notes_enabled(False),
    )
    if watcher is not None:
        runtime_capabilities.register(Capability.CALENDAR, watcher.stop)
    if watcher is not None:
        try:
            watcher.start()
        except Exception:
            LOGGER.warning("Calendar watcher could not start")
    configuration_surface = ConfigurationSurfaceCoordinator(
        event_queue.put,
        runtime_pause=runtime_capabilities,
        prompt_settings=settings,
    )
    RumpsTrayApp(
        controller,
        readiness_report=None,
        configuration_surface=configuration_surface,
    ).run()
    return 0


def _transcription_client(
    configuration: LoadedConfiguration,
    *,
    enabled=lambda: True,
) -> AssemblyAITranscriptionClient | None:
    config = configuration.transcription
    if config is None:
        return None
    try:
        return AssemblyAITranscriptionClient(config.api_key, admit_request=enabled)
    except Exception:
        LOGGER.warning("Transcription capability could not start")
        return None


def _backup_client(
    configuration: LoadedConfiguration,
    *,
    enabled=lambda: True,
) -> B2S3Client | None:
    config = configuration.backup
    if config is None:
        return None
    try:
        return B2S3Client(
            config.application_key_id,
            config.application_key,
            config.endpoint,
            config.region,
            config.bucket_name,
            admit_request=enabled,
        )
    except Exception:
        LOGGER.warning("Backup capability could not start")
        return None


def _notes_generator(configuration: LoadedConfiguration, *, enabled=lambda: True):
    config = configuration.notes
    if config is None:
        return None
    try:
        summarizer = ClaudeSummarizer(
            api_key=config.api_key,
            model=config.model,
            prompt_file=config.prompt_file,
            admit_request=enabled,
        )
    except Exception:
        LOGGER.warning("Notes capability could not start")
        return None

    def generate(path):
        meeting_dir = path if path.is_dir() else path.parent
        return generate_owned_notes(
            configuration.meetings_dir_path,
            meeting_dir,
            summarizer,
        )

    return generate


def _calendar_watcher(
    configuration: LoadedConfiguration,
    event_queue: queue.Queue[object],
    *,
    enabled=lambda: True,
) -> CalendarWatcher | None:
    config = configuration.calendar
    if config is None or not config.credentials_file.is_file():
        return None
    try:
        client = GoogleCalendarClient(
            credentials_file=config.credentials_file,
            calendar_id=config.calendar_id,
            known_speakers=configuration.settings.known_speakers,
            admit_request=enabled,
        )
        return CalendarWatcher(
            client=client,
            event_sink=event_queue.put,
            notify_minutes_before=config.notify_minutes_before,
            poll_interval_seconds=config.poll_interval,
            enabled=enabled,
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
    if client is None or not jobs.transcription_enabled:
        return
    retry_v2_transcriptions(settings.meetings_dir_path, jobs)
    if jobs.transcription_enabled:
        retry_failed_processing(
            settings.meetings_dir_path,
            client,
            enabled=lambda: jobs.transcription_enabled,
        )


def _retry_backups(settings, jobs, client) -> None:
    if client is None or not jobs.backup_enabled:
        return
    retry_v2_backups(settings.meetings_dir_path, jobs)
    if jobs.backup_enabled:
        sync_pending_meetings(
            settings.meetings_dir_path,
            client,
            enabled=lambda: jobs.backup_enabled,
        )


def _run_setup_app() -> int:
    configure_logging()
    RumpsSetupApp(readiness_report=None).run()
    return 0

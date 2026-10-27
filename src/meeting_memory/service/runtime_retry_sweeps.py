"""Existing optional retry sweeps used by runtime composition."""

import logging

from meeting_memory.service.local_transcription import LocalTranscriptAdapter
from meeting_memory.service.processing_retry import retry_failed_processing
from meeting_memory.service.runtime_retry import retry_v2_backups, retry_v2_transcriptions
from meeting_memory.service.sync import sync_pending_meetings
from meeting_memory.types.transcription import TranscriptionProvider

LOGGER = logging.getLogger(__name__)


def _retry_transcriptions(settings, jobs, client) -> None:
    if client is None or not jobs.transcription_enabled:
        return
    retry_v2_transcriptions(settings.meetings_dir_path, jobs)
    if jobs.transcription_enabled:
        retry_failed_processing(
            settings.meetings_dir_path,
            (
                LocalTranscriptAdapter(client, enabled=lambda: jobs.transcription_enabled)
                if getattr(jobs, "transcription_provider", None) is TranscriptionProvider.LOCAL
                else client
            ),
            enabled=lambda: jobs.transcription_enabled,
            event_sink=getattr(jobs, "transcription_event_sink", None),
        )


def _retry_backups(settings, jobs, client) -> None:
    if client is None or not jobs.backup_enabled:
        return
    try:
        retry_v2_backups(settings.meetings_dir_path, jobs)
        if jobs.backup_enabled:
            sync_pending_meetings(
                settings.meetings_dir_path, client, enabled=lambda: jobs.backup_enabled
            )
    except Exception:
        LOGGER.warning("Pending Backup sweep failed", exc_info=True)

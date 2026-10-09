"""Existing optional retry sweeps used by runtime composition."""

import logging

from meeting_memory.service.processing_retry import retry_failed_processing
from meeting_memory.service.runtime_retry import retry_v2_backups, retry_v2_transcriptions
from meeting_memory.service.sync import sync_pending_meetings

LOGGER = logging.getLogger(__name__)


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
    try:
        retry_v2_backups(settings.meetings_dir_path, jobs)
        if jobs.backup_enabled:
            sync_pending_meetings(
                settings.meetings_dir_path, client, enabled=lambda: jobs.backup_enabled
            )
    except Exception:
        LOGGER.warning("Pending Backup sweep failed", exc_info=True)

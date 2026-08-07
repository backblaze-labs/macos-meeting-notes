"""Launch post-recording processing without losing locally saved audio."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path

from meeting_memory.service.recovery import mark_audio_for_recovery
from meeting_memory.types.events import NotifyEvent
from meeting_memory.types.meeting import MeetingMeta

LOGGER = logging.getLogger(__name__)
ThreadFactory = Callable[..., threading.Thread]
ProcessingCallback = Callable[[Path, MeetingMeta], None]
RecoveryMarker = Callable[[Path, MeetingMeta], Path]


def launch_processing(
    *,
    thread_factory: ThreadFactory,
    event_sink: Callable[[object], None],
    callback: ProcessingCallback,
    audio_path: Path,
    meta: MeetingMeta,
    recovery_marker: RecoveryMarker = mark_audio_for_recovery,
) -> bool:
    event_sink(
        NotifyEvent(
            title="Recording saved",
            body=f"{meta.calendar_title} · processing queued",
            show_notification=False,
        )
    )
    try:
        worker = thread_factory(target=callback, args=(audio_path, meta), daemon=True)
        worker.start()
    except Exception as exc:
        LOGGER.exception("Could not launch meeting processing worker")
        recovery_ready = _mark_for_recovery(recovery_marker, audio_path, meta)
        suffix = "Retry from Debugging." if recovery_ready else "The audio remains on disk."
        event_sink(
            NotifyEvent(
                title="Processing could not start",
                body=f"{str(exc).strip() or exc.__class__.__name__}. {suffix}",
            )
        )
        return False
    return True


def _mark_for_recovery(
    marker: RecoveryMarker,
    audio_path: Path,
    meta: MeetingMeta,
) -> bool:
    try:
        marker(audio_path, meta)
    except Exception:
        LOGGER.exception("Could not mark saved audio for recovery")
        return False
    return True

"""Isolated compatibility launcher for pre-schema-v2 recording fakes/data."""

import logging
import threading
from collections.abc import Callable
from pathlib import Path

from meeting_memory.service.pipeline import Pipeline
from meeting_memory.types.events import NotifyEvent
from meeting_memory.types.meeting import MeetingMeta
from meeting_memory.ui.processing_launch import launch_processing

LOGGER = logging.getLogger(__name__)


def launch_legacy_processing(
    pipeline: Pipeline,
    thread_factory: Callable[..., threading.Thread],
    event_sink: Callable[[object], None],
    audio_path: Path,
    meta: MeetingMeta,
) -> None:
    def run(path: Path, meeting_meta: MeetingMeta) -> None:
        try:
            pipeline.run(path, meeting_meta)
        except Exception:
            LOGGER.exception("Legacy meeting processing failed")
            event_sink(NotifyEvent("Meeting processing failed", "Audio remains on disk"))

    launch_processing(
        thread_factory=thread_factory,
        event_sink=event_sink,
        callback=run,
        audio_path=audio_path,
        meta=meta,
    )

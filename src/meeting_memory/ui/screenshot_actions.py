"""Tray screenshot capture and post-commit attachment."""

from __future__ import annotations

import logging

from meeting_memory.service.recorder import RecordingSession
from meeting_memory.service.screenshots import ScreenshotStore
from meeting_memory.types.events import (
    NotifyEvent,
    RecordingCleanupPending,
    RecordingCommitted,
    RecordingPublicationUncertain,
)
from meeting_memory.types.meeting import MeetingRef
from meeting_memory.ui.controller import TrayController

LOGGER = logging.getLogger(__name__)
NO_RECORDING_TITLE = "No active recording"
NO_RECORDING_BODY = "Start a recording to capture screenshots for it."
CAPTURE_FAILED_TITLE = "Screenshot failed"
CAPTURE_FAILED_BODY = "The screen could not be captured. Check Screen Recording permission."
SAVED_TITLE = "Screenshot saved"


class ScreenshotActions:
    """Capture on the main thread; attach when a meeting directory is published."""

    def __init__(self, controller: TrayController, store: ScreenshotStore | None = None) -> None:
        self.controller = controller
        self._store = store

    @property
    def store(self) -> ScreenshotStore:
        if self._store is None:
            self._store = ScreenshotStore(self.controller.settings.meetings_dir_path)
        return self._store

    def take(self) -> None:
        recorder = self.controller.recorder
        session = recorder.active_session
        session_id = recording_session_id(session) if recorder.is_recording else None
        if session is None or session_id is None:
            self._notify(NO_RECORDING_TITLE, NO_RECORDING_BODY)
            return
        try:
            captured = self.store.capture(
                session_id, started_at=session.meta.started_at, now=self.controller.now()
            )
        except Exception:
            LOGGER.warning("Screenshot capture failed", exc_info=True)
            self._notify(CAPTURE_FAILED_TITLE, CAPTURE_FAILED_BODY)
            return
        LOGGER.info("Screenshot %d staged at %s", captured.index, captured.path)
        self._notify(SAVED_TITLE, f"Screenshot {captured.index} · {session.meta.calendar_title}")

    def handle_event(self, event: object) -> tuple[object, ...]:
        meeting = published_meeting(event)
        if meeting is None:
            return ()
        try:
            attached = self.store.attach(meeting)
        except Exception:
            LOGGER.warning("Screenshots could not be attached to %s", meeting.directory)
            LOGGER.debug("Screenshot attachment failed", exc_info=True)
            return ()
        if attached:
            LOGGER.info("Attached %d screenshot(s) to %s", len(attached), meeting.directory)
        return attached

    def _notify(self, title: str, body: str) -> None:
        self.controller.event_queue.put(NotifyEvent(title, body))


def recording_session_id(session: RecordingSession | None) -> str | None:
    """Return the durable capture session name behind an active recording.

    Change this if the recorder ever stages recordings somewhere other than an
    indexed recovery session.
    """

    if session is None or session.recovery is None:
        return None
    return session.recovery.session_directory.name


def published_meeting(event: object) -> MeetingRef | None:
    if isinstance(
        event, (RecordingCommitted, RecordingPublicationUncertain, RecordingCleanupPending)
    ):
        return event.meeting
    return None

"""Tray controller state and background handoff."""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from meeting_memory.config.settings import Settings
from meeting_memory.service.pipeline import Pipeline
from meeting_memory.service.recorder import RecorderService
from meeting_memory.service.recording_context import context_from_meetings
from meeting_memory.service.storage import list_recent_meetings
from meeting_memory.types.events import MeetingDetected, NotifyEvent
from meeting_memory.types.meeting import (
    CalendarMeeting,
    MeetingMeta,
    RecentMeeting,
    RecordingContext,
)
from meeting_memory.ui.macos import open_in_finder

EventQueue = queue.Queue[object]
ThreadFactory = Callable[..., threading.Thread]
RecordingContextProvider = Callable[[], RecordingContext | None]
LOGGER = logging.getLogger(__name__)


@dataclass
class TrayController:
    settings: Settings
    recorder: RecorderService
    pipeline: Pipeline
    event_queue: EventQueue = field(default_factory=queue.Queue)
    opener: Callable[[Path], None] = field(default_factory=lambda: open_in_finder)
    sync_runner: Callable[[], object] | None = None
    thread_factory: ThreadFactory = threading.Thread
    now: Callable[[], datetime] = field(default_factory=lambda: lambda: datetime.now().astimezone())
    recording_context_provider: RecordingContextProvider | None = None
    sleeper: Callable[[float], None] = time.sleep
    _known_meetings: dict[str, CalendarMeeting] = field(default_factory=dict, init=False)
    _recording_token: object | None = field(default=None, init=False)

    def start_recording(
        self,
        calendar_title: str | None = None,
        *,
        ends_at: datetime | None = None,
    ) -> None:
        context = self.recording_context() if calendar_title is None and ends_at is None else None
        title = calendar_title or (context.calendar_title if context else "Untitled")
        reminder_end = ends_at or (context.ends_at if context else None)
        try:
            session = self.recorder.start(calendar_title=title)
        except Exception as exc:
            LOGGER.exception("Failed to start recording")
            self.event_queue.put(
                NotifyEvent(title="Recording could not start", body=_format_exception(exc))
            )
            return
        if session is not None:
            self._recording_token = object()
            self._schedule_stop_reminder(title, reminder_end, self._recording_token)

    def stop_recording(self) -> None:
        try:
            result = self.recorder.stop()
        except Exception as exc:
            LOGGER.exception("Failed to stop recording")
            self.event_queue.put(
                NotifyEvent(title="Recording could not finish", body=_format_exception(exc))
            )
            return
        if result is None:
            return
        self._recording_token = None
        self.event_queue.put(
            NotifyEvent(
                title="Recording saved",
                body=f"{result.meta.calendar_title} · transcribing now",
            )
        )
        thread = self.thread_factory(
            target=self.run_pipeline,
            args=(result.audio_path, result.meta),
            daemon=True,
        )
        thread.start()

    def run_pipeline(self, audio_path: Path, meta: MeetingMeta) -> None:
        try:
            self.pipeline.run(audio_path, meta)
        except Exception as exc:
            LOGGER.exception("Meeting processing failed")
            self.event_queue.put(
                NotifyEvent(title="Meeting processing failed", body=_format_exception(exc))
            )

    def sync_to_b2(self) -> None:
        if self.sync_runner is None:
            return
        self.thread_factory(target=self.sync_runner, daemon=True).start()

    def recent_meetings(self) -> list[RecentMeeting]:
        return list_recent_meetings(self.settings.meetings_dir_path)

    def remember_meeting(self, event: MeetingDetected) -> None:
        self._known_meetings[event.event_id] = CalendarMeeting(
            event_id=event.event_id,
            calendar_title=event.calendar_title,
            starts_at=event.starts_at,
            meeting_url=event.meeting_url,
            ends_at=event.ends_at,
        )

    def recording_context(self) -> RecordingContext | None:
        if self.recording_context_provider is not None:
            try:
                return self.recording_context_provider()
            except Exception as exc:
                LOGGER.exception("Could not resolve recording context")
                self.event_queue.put(NotifyEvent("Calendar lookup failed", _format_exception(exc)))
        return context_from_meetings(list(self._known_meetings.values()), now=self.now())

    def recording_duration_seconds(self) -> int:
        session = self.recorder.active_session
        if session is None:
            return 0
        return max(0, round((self.now() - session.meta.started_at).total_seconds()))

    def open_meetings_folder(self) -> None:
        self.settings.meetings_dir_path.mkdir(parents=True, exist_ok=True)
        self.opener(self.settings.meetings_dir_path)

    def open_meeting(self, meeting: RecentMeeting) -> None:
        self.opener(meeting.directory)

    def drain_events(self) -> list[object]:
        events: list[object] = []
        while True:
            try:
                events.append(self.event_queue.get_nowait())
            except queue.Empty:
                return events

    def _schedule_stop_reminder(
        self,
        calendar_title: str,
        ends_at: datetime | None,
        token: object,
    ) -> None:
        if ends_at is None or ends_at <= self.now():
            return
        self.thread_factory(
            target=self._send_stop_reminder,
            args=(calendar_title, ends_at, token),
            daemon=True,
        ).start()

    def _send_stop_reminder(self, calendar_title: str, ends_at: datetime, token: object) -> None:
        self.sleeper(max(0, (ends_at - self.now()).total_seconds()))
        if self._recording_token is token and self.recorder.is_recording:
            self.event_queue.put(
                NotifyEvent(
                    title="Meeting ending",
                    body=f"{calendar_title} is ending now. Stop recording?",
                    action_label="Stop",
                    action="stop_recording",
                )
            )


def _format_exception(exc: Exception) -> str:
    return str(exc).strip() or exc.__class__.__name__

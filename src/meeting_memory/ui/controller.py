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
from meeting_memory.service.processing_retry import retry_failed_processing
from meeting_memory.service.recorder import RecorderService
from meeting_memory.service.recording_context import context_from_meetings
from meeting_memory.service.recovery import (
    RecoveredRecording,
    convert_recovered_recording,
    find_recovered_recordings,
)
from meeting_memory.service.storage import list_recent_meetings
from meeting_memory.service.transcript_review import (
    confirm_speaker_aliases,
    generate_notes_from_transcript,
    list_speaker_review_meetings,
    load_speaker_review,
)
from meeting_memory.types.events import MeetingDetected, NotifyEvent, RecordingTitleNeeded
from meeting_memory.types.meeting import (
    CalendarMeeting,
    MeetingMeta,
    RecentMeeting,
    RecordingContext,
)
from meeting_memory.types.transcript import SpeakerReviewState
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
    processing_retry_runner: Callable[[], object] | None = None
    thread_factory: ThreadFactory = threading.Thread
    timer_thread_factory: ThreadFactory = threading.Thread
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
        speaker_candidates: tuple[str, ...] = (),
    ) -> None:
        context = self.recording_context() if calendar_title is None and ends_at is None else None
        title = calendar_title or (context.calendar_title if context else "Untitled")
        reminder_end = ends_at or (context.ends_at if context else None)
        candidates = speaker_candidates or (context.speaker_candidates if context else ())
        try:
            session = self.recorder.start(calendar_title=title, speaker_candidates=candidates)
        except Exception as exc:
            LOGGER.exception("Failed to start recording")
            self.event_queue.put(
                NotifyEvent(title="Recording could not start", body=_format_exception(exc))
            )
            return
        if session is not None:
            self._recording_token = object()
            token = self._recording_token
            self._schedule_auto_stop(title, token)
            self._schedule_stop_reminder(title, reminder_end, token)

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

        if result.meta.needs_title_prompt:
            self.event_queue.put(RecordingTitleNeeded(result.audio_path, result.meta))
            return

        self.process_recording(result.audio_path, result.meta)

    def process_recording(self, audio_path: Path, meta: MeetingMeta) -> None:
        self.event_queue.put(
            NotifyEvent(
                title="Recording saved",
                body=f"{meta.calendar_title} · transcribing now",
                show_notification=False,
            )
        )
        thread = self.thread_factory(
            target=self.run_pipeline,
            args=(audio_path, meta),
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

    def retry_failed_processing(self) -> None:
        runner = self.processing_retry_runner or (
            lambda: retry_failed_processing(self.settings.meetings_dir_path, self.pipeline)
        )
        self.thread_factory(target=runner, daemon=True).start()

    def recent_meetings(self) -> list[RecentMeeting]:
        return list_recent_meetings(self.settings.meetings_dir_path)

    def speaker_review_meetings(self) -> list[RecentMeeting]:
        return list_speaker_review_meetings(self.settings.meetings_dir_path)

    def load_speaker_review(self, path: Path) -> SpeakerReviewState:
        return load_speaker_review(path)

    def confirm_speaker_aliases(self, path: Path, aliases: dict[str, str]) -> Path:
        return confirm_speaker_aliases(path, aliases)

    def generate_notes(self, path: Path) -> None:
        self.thread_factory(target=self._generate_notes, args=(path,), daemon=True).start()

    def recovered_recordings(self) -> list[RecoveredRecording]:
        temp_dir = getattr(self.recorder, "temp_dir", None)
        if temp_dir is None:
            return []
        return find_recovered_recordings(temp_dir)

    def process_recovered_recording(self, recording: RecoveredRecording) -> None:
        self.thread_factory(
            target=self._process_recovered_recording,
            args=(recording,),
            daemon=True,
        ).start()

    def remember_meeting(self, event: MeetingDetected) -> None:
        self._known_meetings[event.event_id] = CalendarMeeting(
            event_id=event.event_id,
            calendar_title=event.calendar_title,
            starts_at=event.starts_at,
            meeting_url=event.meeting_url,
            ends_at=event.ends_at,
            speaker_candidates=event.speaker_candidates,
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

    def _schedule_auto_stop(self, calendar_title: str, token: object) -> None:
        self.timer_thread_factory(
            target=self._auto_stop_recording,
            args=(calendar_title, token),
            daemon=True,
        ).start()

    def _auto_stop_recording(self, calendar_title: str, token: object) -> None:
        self.sleeper(self.settings.max_recording_minutes * 60)
        if self._recording_token is token and self.recorder.is_recording:
            self.event_queue.put(
                NotifyEvent(
                    title="Recording limit reached",
                    body=f"{calendar_title} reached {self.settings.max_recording_minutes} min.",
                )
            )
            self.stop_recording()

    def _process_recovered_recording(self, recording: RecoveredRecording) -> None:
        try:
            audio_path = convert_recovered_recording(recording)
        except Exception as exc:
            LOGGER.exception("Recovered recording could not be converted")
            self.event_queue.put(
                NotifyEvent(
                    title="Recovered recording failed",
                    body=_format_exception(exc),
                )
            )
            return

        self.event_queue.put(
            NotifyEvent(
                title="Recovered recording queued",
                body=f"{recording.meta.calendar_title} · transcribing now",
            )
        )
        self.run_pipeline(audio_path, recording.meta)

    def _generate_notes(self, path: Path) -> None:
        summarizer = self.pipeline.summarizer_client
        if summarizer is None:
            event = NotifyEvent("Notes generation failed", "Summarizer not configured")
            self.event_queue.put(event)
            return
        try:
            notes_path = generate_notes_from_transcript(path, summarizer)
        except Exception as exc:
            LOGGER.exception("Notes generation failed")
            self.event_queue.put(NotifyEvent("Notes generation failed", _format_exception(exc)))
            return
        self.event_queue.put(
            NotifyEvent(
                title="Notes generated",
                body=f"{notes_path.parent.name} · notes.md ready",
                action_label="Open",
                meeting_directory=notes_path.parent,
            )
        )


def _format_exception(exc: Exception) -> str:
    return str(exc).strip() or exc.__class__.__name__

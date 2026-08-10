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

from meeting_memory.config.runtime import RuntimeSettings
from meeting_memory.config.settings import Settings
from meeting_memory.service.local_commit import LocalRecordingCommitter
from meeting_memory.service.pipeline import Pipeline
from meeting_memory.service.processing_state import list_pending_processing_tasks
from meeting_memory.service.recorder import RecorderService, RecordingResult
from meeting_memory.service.recording_context import context_from_meetings
from meeting_memory.service.runtime_legacy_recovery import LegacyRecoveryRuntime
from meeting_memory.service.storage import list_recent_meetings
from meeting_memory.service.transcript_review import confirm_speaker_aliases, load_speaker_review
from meeting_memory.types.events import MeetingDetected, NotifyEvent, RecordingTitleNeeded
from meeting_memory.types.meeting import (
    CalendarMeeting,
    MeetingMeta,
    RecentMeeting,
    RecordingContext,
)
from meeting_memory.types.processing import ProcessingTask
from meeting_memory.types.recovery import RecoveryIndexEntry, RecoveryOrigin
from meeting_memory.types.transcript import SpeakerReviewState
from meeting_memory.ui.legacy_processing import launch_legacy_processing
from meeting_memory.ui.macos import open_in_finder
from meeting_memory.ui.recording_transitions import RecordingTransitions
from meeting_memory.ui.recovery_actions import is_active_recovery, list_recoveries

EventQueue = queue.Queue[object]
ThreadFactory = Callable[..., threading.Thread]
LOGGER = logging.getLogger(__name__)

@dataclass
class TrayController:
    settings: Settings | RuntimeSettings
    recorder: RecorderService
    pipeline: Pipeline | None = None
    committer: LocalRecordingCommitter | None = None
    event_queue: EventQueue = field(default_factory=queue.Queue)
    opener: Callable[[Path], None] = field(default_factory=lambda: open_in_finder)
    sync_runner: Callable[[], object] | None = None
    processing_retry_runner: Callable[[], object] | None = None
    notes_generator: Callable[[Path], Path] | None = None
    legacy_recovery: LegacyRecoveryRuntime | None = None
    thread_factory: ThreadFactory = threading.Thread
    timer_thread_factory: ThreadFactory = threading.Thread
    now: Callable[[], datetime] = field(default_factory=lambda: lambda: datetime.now().astimezone())
    recording_context_provider: Callable[[], RecordingContext | None] | None = None
    sleeper: Callable[[float], None] = time.sleep
    _known_meetings: dict[str, CalendarMeeting] = field(default_factory=dict, init=False)
    _recording_token: object | None = field(default=None, init=False)
    _transitions: RecordingTransitions = field(init=False)

    def __post_init__(self) -> None:
        self._transitions = RecordingTransitions(
            self.recorder,
            self.event_queue,
            context_provider=self.recording_context,
            on_started=self._recording_started,
            on_stopped=self._recording_stopped,
            thread_factory=self.thread_factory,
        )

    def start_recording(
        self,
        calendar_title: str | None = None,
        *,
        ends_at: datetime | None = None,
        speaker_candidates: tuple[str, ...] = (),
    ) -> None:
        self._transitions.request_start(
            calendar_title,
            ends_at=ends_at,
            speaker_candidates=speaker_candidates,
        )

    def stop_recording(self) -> None:
        self._transitions.request_stop()

    def _recording_started(self, title: str, reminder_end: datetime | None) -> None:
        self._recording_token = object()
        token = self._recording_token
        self._schedule_auto_stop(title, token)
        self._schedule_stop_reminder(title, reminder_end, token)

    def _recording_stopped(self, result: RecordingResult) -> None:
        self._recording_token = None
        if result.meta.needs_title_prompt:
            self.event_queue.put(
                RecordingTitleNeeded(result.audio_path, result.meta, result.recovery)
            )
            return
        self.process_recording(result.audio_path, result.meta, recovery=result.recovery)

    def process_recording(
        self,
        audio_path: Path,
        meta: MeetingMeta,
        *,
        recovery: RecoveryIndexEntry | None = None,
    ) -> None:
        if self.committer is not None and recovery is not None:
            try:
                self.thread_factory(
                    target=self.run_local_commit, args=(recovery, meta), daemon=True
                ).start()
            except Exception as exc:
                LOGGER.exception("Could not launch local commit worker")
                self.event_queue.put(
                    NotifyEvent("Recording could not finish", _format_exception(exc))
                )
            return
        if self.pipeline is None:
            self.event_queue.put(
                NotifyEvent("Recording could not finish", "Local commit is unavailable")
            )
            return
        launch_legacy_processing(
            self.pipeline,
            self.thread_factory,
            self.event_queue.put,
            audio_path,
            meta,
        )

    def run_local_commit(self, recovery: RecoveryIndexEntry, meta: MeetingMeta) -> bool:
        try:
            if self.committer is None:
                return False
            if is_active_recovery(self.recorder, recovery):
                return False
            return self.committer.commit(recovery, meta) is not None
        except Exception:
            LOGGER.exception("Local meeting commit failed")
            self.event_queue.put(
                NotifyEvent(
                    title="Recording could not finish",
                    body="Audio remains available for recovery.",
                )
            )
            return False

    def sync_to_b2(self) -> None:
        if self.sync_runner is None:
            return
        self.thread_factory(target=self.sync_runner, daemon=True).start()

    def retry_failed_processing(self) -> None:
        if self.processing_retry_runner is not None:
            self.thread_factory(target=self.processing_retry_runner, daemon=True).start()

    def recent_meetings(self) -> list[RecentMeeting]:
        return list_recent_meetings(self.settings.meetings_dir_path)

    def pending_processing_tasks(self) -> list[ProcessingTask]:
        return list_pending_processing_tasks(self.settings.meetings_dir_path)

    def load_speaker_review(self, path: Path) -> SpeakerReviewState:
        return load_speaker_review(path)

    def confirm_speaker_aliases(self, path: Path, aliases: dict[str, str]) -> Path:
        return confirm_speaker_aliases(path, aliases)

    def generate_notes(self, path: Path) -> None:
        self.thread_factory(target=self._generate_notes, args=(path,), daemon=True).start()

    def recovered_recordings(self) -> list[RecoveryIndexEntry]:
        return list_recoveries(self.recorder, self.legacy_recovery)

    def process_recovered_recording(self, recording: RecoveryIndexEntry) -> None:
        if is_active_recovery(self.recorder, recording):
            return
        if recording.origin is RecoveryOrigin.LEGACY_TEMP and self.legacy_recovery is not None:
            self.legacy_recovery.start_commit(recording)
            return
        self.thread_factory(
            target=self.run_local_commit, args=(recording, recording.meta), daemon=True
        ).start()

    def scan_legacy_recoveries(self) -> None:
        if self.legacy_recovery is not None:
            self.legacy_recovery.start_scan()

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
            target=self._send_stop_reminder, args=(calendar_title, ends_at, token), daemon=True
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
            target=self._auto_stop_recording, args=(calendar_title, token), daemon=True
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

    def _generate_notes(self, path: Path) -> None:
        if self.notes_generator is None:
            event = NotifyEvent("Notes generation failed", "Summarizer not configured")
            self.event_queue.put(event)
            return
        try:
            notes_path = self.notes_generator(path)
        except Exception:
            LOGGER.exception("Notes generation failed")
            self.event_queue.put(
                NotifyEvent("Notes generation failed", "Transcript remains saved locally")
            )
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

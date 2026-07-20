"""Background-safe calendar polling service."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from meeting_memory.types.events import MeetingDetected, NotifyEvent
from meeting_memory.types.meeting import CalendarMeeting


class CalendarClient(Protocol):
    def list_upcoming_meetings(
        self,
        *,
        now: datetime,
        lookahead_minutes: int,
        lookbehind_minutes: int = 0,
    ) -> list[CalendarMeeting]:
        """Return upcoming video meetings."""


EventSink = Callable[[object], None]
ThreadFactory = Callable[..., threading.Thread]


@dataclass
class CalendarWatcher:
    client: CalendarClient
    event_sink: EventSink
    notify_minutes_before: int
    poll_interval_seconds: int
    now: Callable[[], datetime] = field(
        default_factory=lambda: lambda: datetime.now().astimezone()
    )
    sleeper: Callable[[float], None] = time.sleep
    thread_factory: ThreadFactory = threading.Thread

    def __post_init__(self) -> None:
        self._seen_event_ids: set[str] = set()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = self.thread_factory(target=self.run_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def run_forever(self) -> None:
        while not self._stop.is_set():
            self.poll_once()
            self.sleeper(self.poll_interval_seconds)

    def poll_once(self) -> None:
        now = self.now()
        try:
            meetings = self.client.list_upcoming_meetings(
                now=now,
                lookahead_minutes=self.notify_minutes_before + 2,
                lookbehind_minutes=self._lookbehind_minutes(),
            )
        except Exception as exc:
            self.event_sink(
                NotifyEvent(
                    title="Calendar watcher error",
                    body=str(exc),
                )
            )
            return

        schedule_until = now + timedelta(minutes=2)
        for meeting in meetings:
            notify_at = meeting.starts_at - timedelta(minutes=self.notify_minutes_before)
            if meeting.event_id in self._seen_event_ids or notify_at > schedule_until:
                continue
            self._seen_event_ids.add(meeting.event_id)
            if notify_at <= now:
                self._emit_meeting_detected(meeting)
            else:
                self._schedule_meeting_detected(meeting, notify_at)

    def _schedule_meeting_detected(self, meeting: CalendarMeeting, notify_at: datetime) -> None:
        thread = self.thread_factory(
            target=self._emit_meeting_detected_after_delay,
            args=(meeting, notify_at),
            daemon=True,
        )
        thread.start()

    def _emit_meeting_detected_after_delay(
        self,
        meeting: CalendarMeeting,
        notify_at: datetime,
    ) -> None:
        self.sleeper(max(0, (notify_at - self.now()).total_seconds()))
        if not self._stop.is_set():
            self._emit_meeting_detected(meeting)

    def _emit_meeting_detected(self, meeting: CalendarMeeting) -> None:
        self.event_sink(
            MeetingDetected(
                event_id=meeting.event_id,
                calendar_title=meeting.calendar_title,
                starts_at=meeting.starts_at,
                meeting_url=meeting.meeting_url,
                ends_at=meeting.ends_at,
                speaker_candidates=meeting.speaker_candidates,
            )
        )

    def _lookbehind_minutes(self) -> int:
        if self.notify_minutes_before > 0:
            return 0
        return max(1, (self.poll_interval_seconds + 59) // 60)

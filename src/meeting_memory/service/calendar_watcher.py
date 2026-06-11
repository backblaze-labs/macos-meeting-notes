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
    ) -> list[CalendarMeeting]:
        """Return upcoming video meetings."""


EventSink = Callable[[object], None]


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

    def __post_init__(self) -> None:
        self._seen_event_ids: set[str] = set()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self.run_forever, daemon=True)
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
            )
        except Exception as exc:
            self.event_sink(
                NotifyEvent(
                    title="Calendar watcher error",
                    body=str(exc),
                )
            )
            return

        notify_until = now + timedelta(minutes=self.notify_minutes_before)
        for meeting in meetings:
            if meeting.event_id in self._seen_event_ids or meeting.starts_at > notify_until:
                continue
            self._seen_event_ids.add(meeting.event_id)
            self.event_sink(
                MeetingDetected(
                    event_id=meeting.event_id,
                    calendar_title=meeting.calendar_title,
                    starts_at=meeting.starts_at,
                    meeting_url=meeting.meeting_url,
                )
            )

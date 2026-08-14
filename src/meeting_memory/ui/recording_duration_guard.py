"""Long-recording reminders and the configured auto-stop boundary."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from meeting_memory.types.events import NotifyEvent

FIRST_REMINDER_MINUTES = 60
REMINDER_INTERVAL_MINUTES = 30

EventSink = Callable[[NotifyEvent], None]
ThreadFactory = Callable[..., threading.Thread]


@dataclass(frozen=True)
class RecordingDurationGuard:
    max_duration_minutes: int
    event_sink: EventSink
    is_active: Callable[[object], bool]
    stop_recording: Callable[[], None]
    thread_factory: ThreadFactory = threading.Thread
    sleeper: Callable[[float], None] = field(default=time.sleep)

    def start(self, calendar_title: str, token: object) -> None:
        self.thread_factory(
            target=self.run,
            args=(calendar_title, token),
            daemon=True,
        ).start()

    def run(self, calendar_title: str, token: object) -> None:
        limit_seconds = self.max_duration_minutes * 60
        elapsed_seconds = 0
        next_reminder_seconds = FIRST_REMINDER_MINUTES * 60

        while next_reminder_seconds < limit_seconds:
            if not self._wait_while_active(
                next_reminder_seconds - elapsed_seconds,
                token,
            ):
                return
            elapsed_seconds = next_reminder_seconds
            elapsed_minutes = elapsed_seconds // 60
            self.event_sink(
                NotifyEvent(
                    title="Recording still active",
                    body=(
                        f"{calendar_title} has been recording for "
                        f"{_duration_label(elapsed_minutes)}."
                    ),
                    action_label="Stop",
                    action="stop_recording",
                )
            )
            next_reminder_seconds += REMINDER_INTERVAL_MINUTES * 60

        if not self._wait_while_active(limit_seconds - elapsed_seconds, token):
            return
        self.event_sink(
            NotifyEvent(
                title="Recording limit reached",
                body=f"{calendar_title} reached {self.max_duration_minutes} min.",
            )
        )
        self.stop_recording()

    def _wait_while_active(self, seconds: int, token: object) -> bool:
        if not self.is_active(token):
            return False
        self.sleeper(seconds)
        return self.is_active(token)


def _duration_label(minutes: int) -> str:
    if minutes % 60 == 0:
        hours = minutes // 60
        return f"{hours} hour" if hours == 1 else f"{hours} hours"
    return f"{minutes} min"

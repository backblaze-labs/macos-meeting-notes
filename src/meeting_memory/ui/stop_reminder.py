"""Meeting-end Stop reminder for recordings with a known calendar end time.

Sleeps on a worker until the event ends, then queues a Stop notification if
the same recording is still active. Extracted from the controller to keep it
under the size limit; change this if reminders ever need a timer instead of
a sleeping thread.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime

from meeting_memory.types.events import NotifyEvent


def schedule_stop_reminder(
    *,
    calendar_title: str,
    ends_at: datetime | None,
    token: object,
    now: Callable[[], datetime],
    sleeper: Callable[[float], None],
    thread_factory: Callable[..., threading.Thread],
    is_active: Callable[[object], bool],
    event_sink: Callable[[object], None],
) -> None:
    """Start the reminder worker when the meeting has an end time still ahead."""

    if ends_at is None or ends_at <= now():
        return

    def remind() -> None:
        sleeper(max(0, (ends_at - now()).total_seconds()))
        if is_active(token):
            event_sink(
                NotifyEvent(
                    title="Meeting ending",
                    body=f"{calendar_title} is ending now. Stop recording?",
                    action_label="Stop",
                    action="stop_recording",
                )
            )

    thread_factory(target=remind, daemon=True).start()

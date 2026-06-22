"""Resolve recording metadata from nearby calendar meetings."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Protocol

from meeting_memory.types.meeting import CalendarMeeting, RecordingContext


class CalendarLookup(Protocol):
    def list_upcoming_meetings(
        self,
        *,
        now: datetime,
        lookahead_minutes: int,
        lookbehind_minutes: int = 0,
    ) -> list[CalendarMeeting]:
        """Return nearby video meetings."""


def current_recording_context(
    calendar_lookup: CalendarLookup,
    *,
    now: datetime,
    window_minutes: int = 5,
) -> RecordingContext | None:
    meetings = calendar_lookup.list_upcoming_meetings(
        now=now,
        lookahead_minutes=window_minutes,
        lookbehind_minutes=window_minutes,
    )
    return context_from_meetings(meetings, now=now, window_minutes=window_minutes)


def context_from_meetings(
    meetings: Sequence[CalendarMeeting],
    *,
    now: datetime,
    window_minutes: int = 5,
) -> RecordingContext | None:
    candidates = [
        meeting
        for meeting in meetings
        if _matches_recording_time(meeting, now=now, window_minutes=window_minutes)
    ]
    if not candidates:
        return None

    meeting = min(candidates, key=lambda item: abs((item.starts_at - now).total_seconds()))
    return RecordingContext(
        calendar_title=meeting.calendar_title,
        ends_at=meeting.ends_at,
        event_id=meeting.event_id,
        speaker_candidates=meeting.speaker_candidates,
    )


def _matches_recording_time(
    meeting: CalendarMeeting,
    *,
    now: datetime,
    window_minutes: int,
) -> bool:
    window = timedelta(minutes=window_minutes)
    if meeting.ends_at is not None:
        return meeting.starts_at - window <= now <= meeting.ends_at
    return abs((meeting.starts_at - now).total_seconds()) <= window.total_seconds()

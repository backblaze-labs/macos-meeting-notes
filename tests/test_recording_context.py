"""Tests for calendar-derived recording context."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from meeting_memory.service.recording_context import current_recording_context
from meeting_memory.types.meeting import CalendarMeeting


def test_current_recording_context_matches_ongoing_meeting() -> None:
    now = datetime(2026, 6, 11, 9, 20, tzinfo=UTC)
    meeting = CalendarMeeting(
        event_id="standup",
        calendar_title="Daily Standup",
        starts_at=datetime(2026, 6, 11, 9, 0, tzinfo=UTC),
        meeting_url="meet",
        ends_at=datetime(2026, 6, 11, 9, 30, tzinfo=UTC),
    )
    lookup = FakeCalendarLookup([meeting])

    context = current_recording_context(lookup, now=now)

    assert context is not None
    assert context.calendar_title == "Daily Standup"
    assert context.ends_at == meeting.ends_at
    assert lookup.calls == [(now, 5, 5)]


def test_current_recording_context_ignores_non_matching_meeting() -> None:
    now = datetime(2026, 6, 11, 9, 20, tzinfo=UTC)
    lookup = FakeCalendarLookup(
        [
            CalendarMeeting(
                event_id="later",
                calendar_title="Planning",
                starts_at=now + timedelta(minutes=30),
                meeting_url="zoom",
            )
        ]
    )

    assert current_recording_context(lookup, now=now) is None


class FakeCalendarLookup:
    def __init__(self, meetings: list[CalendarMeeting]):
        self.meetings = meetings
        self.calls = []

    def list_upcoming_meetings(
        self,
        *,
        now: datetime,
        lookahead_minutes: int,
        lookbehind_minutes: int = 0,
    ) -> list[CalendarMeeting]:
        self.calls.append((now, lookahead_minutes, lookbehind_minutes))
        return self.meetings

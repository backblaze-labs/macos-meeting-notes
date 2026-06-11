"""Tests for background calendar polling."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from meeting_memory.service.calendar_watcher import CalendarWatcher
from meeting_memory.types.events import MeetingDetected, NotifyEvent
from meeting_memory.types.meeting import CalendarMeeting


def test_calendar_watcher_emits_each_meeting_once() -> None:
    now = datetime(2026, 6, 11, 9, 0, tzinfo=UTC)
    events: list[object] = []
    watcher = CalendarWatcher(
        client=FakeCalendarClient(
            [
                CalendarMeeting("soon", "Standup", now + timedelta(minutes=4), "meet"),
                CalendarMeeting("later", "Planning", now + timedelta(minutes=10), "zoom"),
            ]
        ),
        event_sink=events.append,
        notify_minutes_before=5,
        poll_interval_seconds=120,
        now=lambda: now,
    )

    watcher.poll_once()
    watcher.poll_once()

    assert events == [MeetingDetected("soon", "Standup", now + timedelta(minutes=4), "meet")]


def test_calendar_watcher_reports_poll_errors_as_events() -> None:
    events: list[object] = []
    watcher = CalendarWatcher(
        client=FailingCalendarClient(),
        event_sink=events.append,
        notify_minutes_before=5,
        poll_interval_seconds=120,
        now=lambda: datetime(2026, 6, 11, 9, 0, tzinfo=UTC),
    )

    watcher.poll_once()

    assert isinstance(events[0], NotifyEvent)
    assert events[0].title == "Calendar watcher error"
    assert events[0].body == "calendar unavailable"


class FakeCalendarClient:
    def __init__(self, meetings: list[CalendarMeeting]):
        self.meetings = meetings

    def list_upcoming_meetings(self, *, now: datetime, lookahead_minutes: int):
        assert lookahead_minutes == 7
        return self.meetings


class FailingCalendarClient:
    def list_upcoming_meetings(self, *, now: datetime, lookahead_minutes: int):
        raise RuntimeError("calendar unavailable")

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
                CalendarMeeting(
                    "soon",
                    "Standup",
                    now + timedelta(minutes=4),
                    "meet",
                    now + timedelta(minutes=34),
                ),
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

    assert events == [
        MeetingDetected(
            "soon",
            "Standup",
            now + timedelta(minutes=4),
            "meet",
            now + timedelta(minutes=34),
        )
    ]


def test_calendar_watcher_with_zero_schedules_notification_at_meeting_start() -> None:
    now = datetime(2026, 6, 11, 9, 0, tzinfo=UTC)
    events: list[object] = []
    sleeps: list[float] = []
    meeting = CalendarMeeting(
        "starting-soon",
        "Interview",
        now + timedelta(seconds=90),
        "meet",
        now + timedelta(minutes=30),
    )
    watcher = CalendarWatcher(
        client=FakeCalendarClient(
            [meeting],
            expected_lookahead=2,
            expected_lookbehind=2,
        ),
        event_sink=events.append,
        notify_minutes_before=0,
        poll_interval_seconds=120,
        now=lambda: now,
        sleeper=sleeps.append,
        thread_factory=ImmediateThread,
    )

    watcher.poll_once()

    assert sleeps == [90]
    assert events == [
        MeetingDetected(
            "starting-soon",
            "Interview",
            now + timedelta(seconds=90),
            "meet",
            now + timedelta(minutes=30),
        )
    ]


def test_calendar_watcher_with_zero_catches_recently_started_meetings() -> None:
    now = datetime(2026, 6, 11, 9, 0, tzinfo=UTC)
    events: list[object] = []
    client = FakeCalendarClient(
        [
            CalendarMeeting(
                "just-started",
                "Design Review",
                now - timedelta(seconds=30),
                "zoom",
                now + timedelta(minutes=30),
            )
        ],
        expected_lookahead=2,
        expected_lookbehind=2,
    )
    watcher = CalendarWatcher(
        client=client,
        event_sink=events.append,
        notify_minutes_before=0,
        poll_interval_seconds=120,
        now=lambda: now,
    )

    watcher.poll_once()

    assert client.calls == [(2, 2)]
    assert events == [
        MeetingDetected(
            "just-started",
            "Design Review",
            now - timedelta(seconds=30),
            "zoom",
            now + timedelta(minutes=30),
        )
    ]


def test_calendar_watcher_reports_sanitized_poll_errors(caplog) -> None:
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
    assert events[0].body == "Calendar polling failed. Check setup and try again."
    assert "calendar unavailable" not in caplog.text


def test_calendar_pause_after_provider_return_emits_no_meeting() -> None:
    enabled = True
    events: list[object] = []
    now = datetime(2026, 6, 11, 9, 0, tzinfo=UTC)

    class PausingClient:
        def list_upcoming_meetings(self, **_kwargs):
            nonlocal enabled
            enabled = False
            return [CalendarMeeting("event", "Private", now, "meet")]

    watcher = CalendarWatcher(
        client=PausingClient(),
        event_sink=events.append,
        notify_minutes_before=0,
        poll_interval_seconds=120,
        now=lambda: now,
        enabled=lambda: enabled,
    )

    watcher.poll_once()

    assert events == []


def test_calendar_watcher_notifies_once_per_consecutive_outage() -> None:
    events: list[object] = []
    client = RecoveringCalendarClient()
    watcher = CalendarWatcher(
        client=client,
        event_sink=events.append,
        notify_minutes_before=5,
        poll_interval_seconds=120,
        now=lambda: datetime(2026, 6, 11, 9, 0, tzinfo=UTC),
    )

    watcher.poll_once()
    watcher.poll_once()
    client.available = True
    watcher.poll_once()
    client.available = False
    watcher.poll_once()

    assert [event.title for event in events if isinstance(event, NotifyEvent)] == [
        "Calendar watcher error",
        "Calendar watcher error",
    ]


class FakeCalendarClient:
    def __init__(
        self,
        meetings: list[CalendarMeeting],
        *,
        expected_lookahead: int = 7,
        expected_lookbehind: int = 0,
    ):
        self.meetings = meetings
        self.expected_lookahead = expected_lookahead
        self.expected_lookbehind = expected_lookbehind
        self.calls: list[tuple[int, int]] = []

    def list_upcoming_meetings(
        self,
        *,
        now: datetime,
        lookahead_minutes: int,
        lookbehind_minutes: int = 0,
    ):
        del now
        self.calls.append((lookahead_minutes, lookbehind_minutes))
        assert lookahead_minutes == self.expected_lookahead
        assert lookbehind_minutes == self.expected_lookbehind
        return self.meetings


class FailingCalendarClient:
    def list_upcoming_meetings(
        self,
        *,
        now: datetime,
        lookahead_minutes: int,
        lookbehind_minutes: int = 0,
    ):
        del now, lookahead_minutes, lookbehind_minutes
        raise RuntimeError("calendar unavailable")


class RecoveringCalendarClient:
    def __init__(self) -> None:
        self.available = False

    def list_upcoming_meetings(
        self,
        *,
        now: datetime,
        lookahead_minutes: int,
        lookbehind_minutes: int = 0,
    ):
        del now, lookahead_minutes, lookbehind_minutes
        if not self.available:
            raise RuntimeError("calendar unavailable")
        return []


class ImmediateThread:
    def __init__(self, *, target, args=(), daemon=None):
        del daemon
        self.target = target
        self.args = args

    def start(self) -> None:
        self.target(*self.args)

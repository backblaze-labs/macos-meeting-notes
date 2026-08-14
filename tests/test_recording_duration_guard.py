"""Tests for long-recording reminders and the final auto-stop."""

from __future__ import annotations

from meeting_memory.types.events import NotifyEvent
from meeting_memory.ui.recording_duration_guard import RecordingDurationGuard


def test_reminds_at_one_hour_then_every_half_hour_before_auto_stop() -> None:
    sleeps: list[int] = []
    events: list[NotifyEvent] = []
    stops: list[bool] = []
    token = object()
    guard = RecordingDurationGuard(
        180,
        events.append,
        lambda candidate: candidate is token,
        lambda: stops.append(True),
        sleeper=sleeps.append,
    )

    guard.run("Product Sync", token)

    assert sleeps == [3600, 1800, 1800, 1800, 1800]
    assert events == [
        _reminder("Product Sync", "1 hour"),
        _reminder("Product Sync", "90 min"),
        _reminder("Product Sync", "2 hours"),
        _reminder("Product Sync", "150 min"),
        NotifyEvent("Recording limit reached", "Product Sync reached 180 min."),
    ]
    assert stops == [True]


def test_stopped_recording_cancels_later_reminders_and_auto_stop() -> None:
    active = True
    sleeps: list[int] = []
    events: list[NotifyEvent] = []
    stops: list[bool] = []
    token = object()

    def emit(event: NotifyEvent) -> None:
        nonlocal active
        events.append(event)
        active = False

    guard = RecordingDurationGuard(
        180,
        emit,
        lambda candidate: candidate is token and active,
        lambda: stops.append(True),
        sleeper=sleeps.append,
    )

    guard.run("Product Sync", token)

    assert sleeps == [3600]
    assert events == [_reminder("Product Sync", "1 hour")]
    assert stops == []


def test_auto_stop_replaces_reminder_when_limit_is_one_hour() -> None:
    events: list[NotifyEvent] = []
    stops: list[bool] = []
    token = object()
    guard = RecordingDurationGuard(
        60,
        events.append,
        lambda candidate: candidate is token,
        lambda: stops.append(True),
        sleeper=lambda _seconds: None,
    )

    guard.run("Product Sync", token)

    assert events == [NotifyEvent("Recording limit reached", "Product Sync reached 60 min.")]
    assert stops == [True]


def _reminder(title: str, duration: str) -> NotifyEvent:
    return NotifyEvent(
        "Recording still active",
        f"{title} has been recording for {duration}.",
        action_label="Stop",
        action="stop_recording",
    )

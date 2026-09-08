"""Notification delivery helpers."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from meeting_memory.types.events import MeetingDetected, NotifyEvent
from meeting_memory.ui.macos import deliver_notification, display_notification


def send_notification(
    rumps_module: Any,
    title: str,
    subtitle: str,
    message: str,
    logger: logging.Logger,
    **kwargs,
) -> None:
    kwargs.setdefault("ignoreDnD", True)
    try:
        if getattr(rumps_module, "__name__", "") == "rumps":
            logger.info("Sending notification through UserNotifications: %s", title)
            deliver_notification(rumps_module, title, subtitle, message, **kwargs)
        else:
            logger.info("Sending notification through rumps: %s", title)
            rumps_module.notification(title, subtitle, message, **kwargs)
    except Exception:
        logger.exception("Failed to send notification through rumps")
        display_notification(title, subtitle, message, logger)


def notify_event_kwargs(event: NotifyEvent) -> dict[str, object]:
    kwargs: dict[str, object] = {}
    if event.action_label:
        kwargs["action_button"] = event.action_label
    data = {}
    if event.action:
        data["action"] = event.action
    if event.meeting_directory is not None:
        data.setdefault("action", "open_meeting")
        data["meeting_directory"] = str(event.meeting_directory)
    if data:
        kwargs["data"] = data
    return kwargs


def meeting_detected_notification(event: MeetingDetected) -> tuple[str, str, dict[str, object]]:
    minutes = max(0, round((event.starts_at - datetime.now().astimezone()).total_seconds() / 60))
    message = f"{event.calendar_title} starts in {minutes} minutes"
    kwargs: dict[str, object] = {
        "action_button": "Record",
        "data": {
            "action": "start_recording",
            "calendar_title": event.calendar_title,
            "ends_at": event.ends_at.isoformat() if event.ends_at is not None else "",
            "speaker_candidates": ",".join(event.speaker_candidates),
            "meeting_url": event.meeting_url,
        },
    }
    return "Meeting starting soon", message, kwargs


def parse_notification_datetime(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def parse_notification_candidates(value: object) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(part.strip() for part in str(value).split(",") if part.strip())

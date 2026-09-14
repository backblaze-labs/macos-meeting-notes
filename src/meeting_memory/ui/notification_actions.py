"""Dispatch of macOS notification button clicks back into the tray.

Extracted from ``tray.py`` to keep it under the size limit. Add a branch here
when a notification gains a new action value.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from meeting_memory.ui.macos import dismiss_delivered_notification
from meeting_memory.ui.notifications import (
    parse_notification_candidates,
    parse_notification_datetime,
)

LOGGER = logging.getLogger(__name__)


def dispatch_notification(app: Any, data: object) -> None:
    """Route one notification payload to the matching tray action."""

    if not isinstance(data, dict):
        return
    action = data.get("action")
    if action == "start_recording":
        dismiss_delivered_notification(data, LOGGER)
        app.controller.start_recording(
            str(data.get("calendar_title") or "Untitled"),
            ends_at=parse_notification_datetime(data.get("ends_at")),
            speaker_candidates=parse_notification_candidates(data.get("speaker_candidates")),
        )
        # One click does both, Granola-style: start recording *and* join.
        meeting_url = str(data.get("meeting_url") or "")
        if meeting_url:
            app.open_url(meeting_url)
        app.refresh_sidebar()
    elif action == "stop_recording":
        app.controller.stop_recording()
        app.refresh_sidebar()
    elif action == "open_meeting":
        directory = data.get("meeting_directory")
        if directory:
            app.controller.opener(Path(str(directory)))
    elif action == "review_speakers":
        directory = data.get("meeting_directory")
        if directory:
            app.open_speaker_review(Path(str(directory)))

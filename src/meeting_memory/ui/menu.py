"""Tray menu label helpers."""

from __future__ import annotations

from meeting_memory.types.meeting import RecentMeeting

APP_TITLE = "● Meeting Memory"
RECENT_HEADER = "Recent Meetings"
NO_MEETINGS_LABEL = "No meetings yet"
RECOVERED_HEADER = "Recovered Recordings"
NO_RECOVERED_LABEL = "No recovered recordings"
OPEN_MEETINGS_LABEL = "Open Meetings Folder"
SYNC_LABEL = "Sync to B2"
RETRY_PROCESSING_LABEL = "Retry Failed Processing"
RUN_DIAGNOSTICS_LABEL = "Run Diagnostics"
TEST_NOTIFICATION_LABEL = "Send Test Notification"
PREFERENCES_LABEL = "Preferences..."
QUIT_LABEL = "Quit"


def recording_label(*, is_recording: bool, duration_seconds: int = 0) -> str:
    if is_recording:
        return f"■ Stop Recording · {_format_duration(duration_seconds)}"
    return "▶ Start Recording"


def tray_title(*, is_recording: bool, duration_seconds: int = 0) -> str | None:
    if not is_recording:
        return None
    return _format_duration(duration_seconds)


def recent_meeting_label(meeting: RecentMeeting) -> str:
    return f"{meeting.started_at:%Y-%m-%d %H:%M} · {meeting.calendar_title}"


def recent_meeting_labels(meetings: list[RecentMeeting]) -> list[str]:
    if not meetings:
        return [NO_MEETINGS_LABEL]
    return [recent_meeting_label(meeting) for meeting in meetings[:5]]


def recovered_recording_label(slug: str) -> str:
    return f"Recover {slug}"


def _format_duration(duration_seconds: int) -> str:
    minutes, seconds = divmod(max(0, duration_seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"

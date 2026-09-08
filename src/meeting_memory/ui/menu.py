"""Label helpers shared by the sidebar view model and the setup tray menu."""

from __future__ import annotations

from meeting_memory.types.meeting import RecentMeeting

APP_TITLE = "● Meeting Memory"
SCREENSHOT_SHORTCUT = "⌥⇧S"
SCREENSHOT_LABEL = f"📷 Take Screenshot ({SCREENSHOT_SHORTCUT})"
RECENT_HEADER = "Recent Meetings"
AUDIO_MODE_HEADER = "Audio Mode"
CONFIGURATION_LABEL = "Configuration"
DEBUGGING_LABEL = "Debugging"
NO_MEETINGS_LABEL = "No meetings yet"
RECOVERED_HEADER = "Interrupted Recordings"
LEGACY_RECOVERY_SCAN_LABEL = "Find Legacy Recordings..."
NO_RECOVERED_LABEL = "No recovered recordings"
OPEN_MEETINGS_LABEL = "Open Meetings Folder"
SYNC_LABEL = "Retry Pending B2 Backups"
RETRY_PROCESSING_LABEL = "Retry Failed Transcriptions"
RUN_DIAGNOSTICS_LABEL = "Check Setup & Dependencies"
TEST_NOTIFICATION_LABEL = "Test macOS Notifications"
NOTES_PROMPT_LABEL = "Notes Customization..."
IMPORT_LEGACY_LABEL = "Import Legacy Configuration..."
AUTHORIZE_CALENDAR_LABEL = "Authorize Google Calendar..."
QUIT_LABEL = "Quit"


def recording_label(
    *,
    is_recording: bool,
    duration_seconds: int = 0,
    audio_warning: bool = False,
) -> str:
    if is_recording:
        prefix = "⚠︎ " if audio_warning else ""
        return f"{prefix}■ Stop Recording · {_format_duration(duration_seconds)}"
    return "▶ Start Recording"


def recent_meeting_label(meeting: RecentMeeting) -> str:
    return f"{meeting.started_at:%Y-%m-%d %H:%M} · {meeting.calendar_title}"


def recovered_header_label(count: int) -> str:
    return f"{RECOVERED_HEADER} ({count})"


def recent_meeting_labels(meetings: list[RecentMeeting]) -> list[str]:
    if not meetings:
        return [NO_MEETINGS_LABEL]
    return [recent_meeting_label(meeting) for meeting in meetings[:3]]


def recovered_recording_label(slug: str) -> str:
    return f"Recover {slug}"


def _format_duration(duration_seconds: int) -> str:
    minutes, seconds = divmod(max(0, duration_seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"

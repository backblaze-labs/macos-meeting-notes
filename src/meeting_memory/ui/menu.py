"""Tray menu label helpers."""

from __future__ import annotations

from meeting_memory.types.meeting import RecentMeeting
from meeting_memory.types.processing import ProcessingTask

APP_TITLE = "● Meeting Memory"
RECENT_HEADER = "Recent Meetings"
AUDIO_MODE_HEADER = "Audio Mode"
CONFIGURATION_LABEL = "Configuration"
DEBUGGING_LABEL = "Debugging"
NO_MEETINGS_LABEL = "No meetings yet"
REVIEW_SPEAKERS_HEADER = "Review Speakers"
PROCESSING_HEADER = "Pending Meeting Tasks"
RECOVERED_HEADER = "Interrupted Recordings"
NO_RECOVERED_LABEL = "No recovered recordings"
OPEN_MEETINGS_LABEL = "Open Meetings Folder"
SYNC_LABEL = "Retry Pending B2 Backups"
RETRY_PROCESSING_LABEL = "Retry Failed Transcriptions"
RUN_DIAGNOSTICS_LABEL = "Check Setup & Dependencies"
TEST_NOTIFICATION_LABEL = "Test macOS Notifications"
KNOWN_SPEAKERS_LABEL = "Known Speakers..."
NOTES_PROMPT_LABEL = "Notes Prompt..."
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


def review_speakers_label(meeting: RecentMeeting) -> str:
    return f"{meeting.started_at:%Y-%m-%d %H:%M} · Review speakers · {meeting.calendar_title}"


def processing_task_label(task: ProcessingTask) -> str:
    meeting = task.meeting
    return f"{meeting.started_at:%Y-%m-%d %H:%M} · {task.label} · {meeting.calendar_title}"


def processing_header_label(count: int) -> str:
    return f"{PROCESSING_HEADER} ({count})"


def processing_task_tooltip(task: ProcessingTask) -> str:
    if task.action == "review_speakers":
        return "Confirm who each speaker is, then generate notes."
    if task.status in {"failed", "skipped"}:
        return "Retry notes generation for this meeting."
    return "Generate notes from the reviewed transcript."


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

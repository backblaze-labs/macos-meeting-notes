"""Exact tray notification mapping for local-first runtime events."""

from meeting_memory.types.events import (
    NotifyEvent,
    RecordingCleanupPending,
    RecordingCommitted,
    RecordingPublicationUncertain,
    TranscriptionFailed,
    TranscriptReady,
)


def runtime_notification(event: object) -> NotifyEvent | None:
    if isinstance(event, RecordingCommitted):
        return NotifyEvent(
            "Recording saved",
            f"{event.meeting.calendar_title} · audio saved locally",
            action_label="Reveal",
            action="open_meeting",
            meeting_directory=event.meeting.directory,
        )
    if isinstance(event, RecordingPublicationUncertain):
        return NotifyEvent(
            "Recording save not confirmed",
            f"{event.meeting.calendar_title} · visible locally; durability not confirmed",
            action_label="Reveal",
            action="open_meeting",
            meeting_directory=event.meeting.directory,
        )
    if isinstance(event, RecordingCleanupPending):
        return NotifyEvent(
            "Recording cleanup pending",
            f"{event.meeting.calendar_title} · retry recovery before cloud processing",
            action_label="Reveal",
            action="open_meeting",
            meeting_directory=event.meeting.directory,
        )
    if isinstance(event, TranscriptReady):
        return NotifyEvent(
            "Transcript ready",
            f"{event.meeting.calendar_title} · review speakers",
            action_label="Review Speakers",
            action="review_speakers",
            meeting_directory=event.meeting.directory,
        )
    if isinstance(event, TranscriptionFailed):
        return NotifyEvent(
            "Transcription failed",
            f"{event.meeting.calendar_title} · audio saved locally",
            action_label="Open",
            action="open_meeting",
            meeting_directory=event.meeting.directory,
        )
    return None

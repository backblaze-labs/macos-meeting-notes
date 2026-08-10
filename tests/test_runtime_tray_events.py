from pathlib import Path

from meeting_memory.types.events import (
    RecordingCleanupPending,
    RecordingCommitted,
    RecordingPublicationUncertain,
    TranscriptionFailed,
    TranscriptReady,
)
from meeting_memory.types.meeting import MeetingRef
from meeting_memory.ui.notifications import notify_event_kwargs
from meeting_memory.ui.runtime_events import runtime_notification


def test_runtime_events_map_to_exact_local_first_copy_and_actions(tmp_path: Path) -> None:
    meeting = MeetingRef("2026-08-10_10-00_sync", "Product Sync", tmp_path)
    mapped = [
        runtime_notification(event)
        for event in (
            RecordingCommitted(meeting),
            RecordingPublicationUncertain(meeting),
            RecordingCleanupPending(meeting),
            TranscriptReady(meeting),
            TranscriptionFailed(meeting),
        )
    ]

    assert [(event.title, event.body) for event in mapped if event is not None] == [
        ("Recording saved", "Product Sync · audio saved locally"),
        (
            "Recording save not confirmed",
            "Product Sync · visible locally; durability not confirmed",
        ),
        (
            "Recording cleanup pending",
            "Product Sync · retry recovery before cloud processing",
        ),
        ("Transcript ready", "Product Sync · review speakers"),
        ("Transcription failed", "Product Sync · audio saved locally"),
    ]
    assert [event.action_label for event in mapped if event is not None] == [
        "Reveal",
        "Reveal",
        "Reveal",
        "Review Speakers",
        "Open",
    ]
    assert [notify_event_kwargs(event)["data"]["action"] for event in mapped if event] == [
        "open_meeting",
        "open_meeting",
        "open_meeting",
        "review_speakers",
        "open_meeting",
    ]

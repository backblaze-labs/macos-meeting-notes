"""Prepare speaker proposals before notification and reuse them for review."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from meeting_memory.service.speaker_suggestions import review_identity
from meeting_memory.service.transcript_review import load_speaker_review
from meeting_memory.types.events import NotifyEvent, SpeakerReviewReady
from meeting_memory.types.meeting import MeetingRef
from meeting_memory.types.transcript import SpeakerReviewState
from meeting_memory.ui.speaker_review import SpeakerReviewActions, open_speaker_review_window


class SpeakerReviewFlow:
    def __init__(self, controller, rumps, refresh) -> None:
        self._controller = controller
        self._rumps = rumps
        self._refresh = refresh
        self._pending: set[Path] = set()
        self._open_requested: set[Path] = set()
        self._prepared: dict[Path, SpeakerReviewState] = {}

    def prepare(self, meeting: MeetingRef) -> None:
        """Start proposals after transcription, before offering Review Speakers."""
        self._prepared.pop(meeting.directory, None)
        self._start(meeting.directory, meeting.calendar_title)

    def open(self, path: Path) -> None:
        self._open_requested.add(path)
        if path in self._pending:
            return
        if state := self._prepared.pop(path, None):
            self.handle_event(SpeakerReviewReady(state, path))
            return
        self._start(path)

    def _start(self, path: Path, title: str | None = None) -> None:
        if path in self._pending:
            return
        self._pending.add(path)
        try:
            self._controller.thread_factory(
                target=self._prepare, args=(path, title), daemon=True
            ).start()
        except Exception:
            self._pending.discard(path)
            self._open_requested.discard(path)
            self._controller.event_queue.put(
                NotifyEvent("Speaker review unavailable", "Could not prepare review. Try again.")
            )

    def _prepare(self, path: Path, title: str | None = None) -> None:
        try:
            state = self._controller.load_speaker_review(path)
            self._controller.event_queue.put(SpeakerReviewReady(state, path, title))
        except Exception:
            self._controller.event_queue.put(
                NotifyEvent(
                    "Speaker review unavailable",
                    "Could not read transcript. Open the meeting folder to check it.",
                    meeting_directory=path,
                    action="open_meeting",
                    action_label="Open",
                )
            )
            self._pending.discard(path)
            self._open_requested.discard(path)

    def handle_event(self, event: object) -> bool:
        if not isinstance(event, SpeakerReviewReady):
            return False
        path = event.requested_path or event.state.meeting_directory
        self._pending.discard(path)
        try:
            current = load_speaker_review(event.state.transcript_path)
        except Exception:
            self._open_requested.discard(path)
            self._controller.event_queue.put(
                NotifyEvent("Speaker review unavailable", "Transcript unavailable. Try again.")
            )
            return True
        if review_identity(current) != review_identity(event.state):
            self._start(path, event.calendar_title)
            return True
        state = event.state
        if not getattr(self._controller, "notes_allowed", lambda: True)():
            state = replace(
                state,
                speaker_suggestions={},
                speaker_evidence={},
                suggestion_message="Notes is paused. Assign names manually.",
            )
        if path not in self._open_requested and event.calendar_title is not None:
            self._prepared[path] = state
            self._controller.event_queue.put(
                NotifyEvent(
                    "Transcript ready",
                    f"{event.calendar_title} · review speakers",
                    action_label="Review Speakers",
                    action="review_speakers",
                    meeting_directory=path,
                )
            )
            self._refresh()
            return True
        self._open_requested.discard(path)
        self._prepared[path] = state
        open_speaker_review_window(
            state.meeting_directory,
            SpeakerReviewActions(
                load_review=lambda _path: state,
                confirm_aliases=self._controller.confirm_speaker_aliases,
                keep_labels=self._controller.keep_speaker_labels,
                generate_notes=self._controller.generate_notes,
            ),
            rumps_module=self._rumps,
        )
        self._refresh()
        return True

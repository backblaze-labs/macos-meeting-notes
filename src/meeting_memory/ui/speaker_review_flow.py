"""Background speaker proposals and main-thread review presentation."""

from __future__ import annotations

from pathlib import Path

from meeting_memory.service.speaker_suggestions import review_identity
from meeting_memory.service.transcript_review import load_speaker_review
from meeting_memory.types.events import NotifyEvent, SpeakerReviewReady
from meeting_memory.ui.speaker_review import SpeakerReviewActions, open_speaker_review_window


class SpeakerReviewFlow:
    def __init__(self, controller, rumps, refresh) -> None:
        self._controller = controller
        self._rumps = rumps
        self._refresh = refresh
        self._pending: set[Path] = set()

    def open(self, path: Path) -> None:
        if path in self._pending:
            return
        self._pending.add(path)
        self._controller.event_queue.put(
            NotifyEvent(
                "Review Speakers",
                "Preparing review. For known attendees, Claude Haiku uses local transcript "
                "text and known-person context to suggest names.",
            )
        )
        try:
            self._controller.thread_factory(target=self._prepare, args=(path,), daemon=True).start()
        except Exception:
            self._pending.discard(path)
            self._controller.event_queue.put(
                NotifyEvent(
                    "Review Speakers",
                    "Could not open review. Try Review Speakers again.",
                )
            )

    def _prepare(self, path: Path) -> None:
        try:
            state = self._controller.load_speaker_review(path)
            self._controller.event_queue.put(SpeakerReviewReady(state, path))
        except Exception:
            self._controller.event_queue.put(
                NotifyEvent(
                    "Review Speakers",
                    "Could not read transcript. Open the meeting folder to check it.",
                    meeting_directory=path,
                    action="open",
                    action_label="Open",
                )
            )
            self._pending.discard(path)

    def handle_event(self, event: object) -> bool:
        if not isinstance(event, SpeakerReviewReady):
            return False
        self._pending.discard(event.requested_path or event.state.meeting_directory)
        try:
            current = load_speaker_review(event.state.transcript_path)
        except Exception:
            self._controller.event_queue.put(
                NotifyEvent(
                    "Review Speakers",
                    "Transcript unavailable. Open the meeting folder to check it.",
                )
            )
            return True
        state = event.state if review_identity(current) == review_identity(event.state) else current
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

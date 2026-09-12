"""Opt-in automatic Notes after transcription.

Off by default: the transcript-ready notification offers manual speaker
review, and Notes start after the user confirms names or keeps the labels.
When on, the diarized labels are kept as-is and Notes start at once, with the
Calendar attendee list handed to the summarizer as context. The transcript
never gains real names this way, and Notes can still attribute a person
incorrectly, so enabling it requires an explicit confirmation that states
that tradeoff.

The value is UI-level session behavior stored in ``NSUserDefaults`` next to
the sidebar preferences, not app configuration in the preference document.
Change the storage here if it ever needs to migrate or sync between Macs.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from meeting_memory.ui.sidebar_view_model import RowView

AUTOMATIC_NOTES_KEY = "MeetingMemoryAutomaticNotes"
AUTOMATIC_NOTES_LABEL = "Automatic Notes from Calendar attendees"
AUTOMATIC_NOTES_TOOLTIP = "Skip manual speaker review and generate Notes right after transcription."
CONFIRM_TITLE = "Turn on automatic Notes?"
CONFIRM_MESSAGE = (
    "After each transcription, Meeting Memory will skip manual speaker review "
    "and generate Notes right away, giving the summarizer the meeting's Calendar "
    "attendees as context.\n\n"
    "Speaker labels such as Speaker A stay in the transcript; no real names are "
    "assigned. Notes may still attribute a statement or task to the wrong person. "
    "You can reopen Review Speakers from Debugging to correct a meeting afterwards.\n\n"
    "Notes must be configured for this to run. Turn it off here at any time."
)
CONFIRM_OK = "Turn On"
CONFIRM_CANCEL = "Cancel"
ALERT_OK_RESPONSE = 1


class MemoryDefaults:
    """In-process stand-in for NSUserDefaults, used by tests and headless runs."""

    def __init__(self) -> None:
        self._values: dict[str, bool] = {}

    def boolForKey_(self, key: str) -> bool:
        return self._values.get(key, False)

    def setBool_forKey_(self, value: bool, key: str) -> None:
        self._values[key] = bool(value)


def standard_defaults() -> Any:
    """Return the real NSUserDefaults; imported lazily so tests stay headless."""

    import Foundation

    return Foundation.NSUserDefaults.standardUserDefaults()


class NotesMode:
    """Read, confirm, and store the automatic-Notes opt-in."""

    def __init__(self, defaults: Any) -> None:
        self._defaults = defaults

    def enabled(self) -> bool:
        return bool(self._defaults.boolForKey_(AUTOMATIC_NOTES_KEY))

    def set_enabled(self, value: bool) -> None:
        self._defaults.setBool_forKey_(bool(value), AUTOMATIC_NOTES_KEY)

    def label(self) -> str:
        """Checkmark-prefixed, matching the audio-mode and sidebar preference rows."""

        prefix = "\u2713 " if self.enabled() else ""
        return f"{prefix}{AUTOMATIC_NOTES_LABEL}"

    def toggle(self, rumps: Any) -> bool:
        """Flip the setting; turning it on first asks the user to accept the tradeoff."""

        if self.enabled():
            self.set_enabled(False)
            return False
        if not confirm_enable(rumps):
            return False
        self.set_enabled(True)
        return True

    def rows(self, rumps: Any, *, on_change: Callable[[], None]) -> tuple[RowView, ...]:
        """The Configuration submenu row for this setting."""

        def toggle() -> None:
            self.toggle(rumps)
            on_change()

        return (RowView(label=self.label(), tooltip=AUTOMATIC_NOTES_TOOLTIP, action=toggle),)


def confirm_enable(rumps: Any) -> bool:
    """Show the tradeoff and return True only when the user chooses Turn On."""

    alert = getattr(rumps, "alert", None)
    if not callable(alert):
        return False
    response = alert(
        title=CONFIRM_TITLE, message=CONFIRM_MESSAGE, ok=CONFIRM_OK, cancel=CONFIRM_CANCEL
    )
    return int(response or 0) == ALERT_OK_RESPONSE

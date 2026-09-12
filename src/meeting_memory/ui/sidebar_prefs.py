"""Sidebar-only preferences, persisted to `NSUserDefaults` like the panel
frame, anchor, and section state — UI chrome, not app configuration.

`hide_while_recording`: when on, the auto-show that normally happens when a
recording starts (docs/features/sidebar.md) is suppressed for the whole
session. The panel is never hidden by the app; the user can still open it
from Show Sidebar. Off by default; the user opts in from Configuration.
"""

from __future__ import annotations

from typing import Any

HIDE_WHILE_RECORDING_KEY = "MeetingMemorySidebarHideWhileRecording"
HIDE_WHILE_RECORDING_LABEL = "Hide sidebar while recording"


def hide_while_recording(appkit: Any) -> bool:
    return bool(appkit.NSUserDefaults.standardUserDefaults().boolForKey_(HIDE_WHILE_RECORDING_KEY))


def set_hide_while_recording(appkit: Any, value: bool) -> None:
    appkit.NSUserDefaults.standardUserDefaults().setBool_forKey_(value, HIDE_WHILE_RECORDING_KEY)


def hide_while_recording_label(appkit: Any) -> str:
    """Checkmark-prefixed, matching the audio-mode rows' convention."""

    prefix = "✓ " if hide_while_recording(appkit) else ""
    return f"{prefix}{HIDE_WHILE_RECORDING_LABEL}"

"""Collapsible-section expand/collapsed state for the vertical layout.

Persisted to `NSUserDefaults` alongside the panel frame and anchor (plan 02),
under its own key — this is UI chrome, not app configuration.
"""

from __future__ import annotations

from typing import Any

SECTION_DEFAULTS_KEY = "MeetingMemorySidebarSections"

# "Recent / Pending open; Configuration / Diagnostics collapsed" — live work
# stays visible, settings are one click away.
DEFAULT_EXPANDED = ("recent", "pending")


class SectionState:
    def __init__(self, appkit: Any) -> None:
        self._appkit = appkit
        self._expanded = set(self._load())

    def is_expanded(self, key: str) -> bool:
        return key in self._expanded

    def toggle(self, key: str) -> bool:
        if key in self._expanded:
            self._expanded.discard(key)
        else:
            self._expanded.add(key)
        self._save()
        return key in self._expanded

    def _load(self) -> tuple[str, ...]:
        stored = self._appkit.NSUserDefaults.standardUserDefaults().arrayForKey_(
            SECTION_DEFAULTS_KEY
        )
        if stored is None:
            return DEFAULT_EXPANDED
        return tuple(stored)

    def _save(self) -> None:
        self._appkit.NSUserDefaults.standardUserDefaults().setObject_forKey_(
            sorted(self._expanded), SECTION_DEFAULTS_KEY
        )

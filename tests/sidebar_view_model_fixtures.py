"""Convenience `SidebarViewModel` fixtures for sidebar layout tests.

Plan 04 landed `ui/sidebar_view_model.py` mid-way through plan 05's build, so
these import the real dataclasses directly — `sidebar_vertical.py` and
`sidebar_widgets.py` themselves stay duck-typed and never import this module
or the real one, but tests are free to exercise the genuine contract.
"""

from __future__ import annotations

from meeting_memory.ui.sidebar_view_model import (
    RecordingView,
    RowView,
    SectionView,
    SidebarViewModel,
)

__all__ = ["RecordingView", "RowView", "SectionView", "SidebarViewModel", "idle_view_model"]


def idle_view_model() -> SidebarViewModel:
    return SidebarViewModel(
        recording=RecordingView(
            is_recording=False, duration_seconds=0, audio_warning=False, label="▶ Start Recording"
        ),
        audio_modes=(
            RowView("✓ Full Meeting", tooltip="Record microphone and system audio"),
            RowView("Silent System Only", tooltip="Record system audio only"),
        ),
        recent=SectionView(
            "Recent Meetings",
            rows=(RowView("2026-09-05 14:00 · Standup", tooltip="Open notes"),),
        ),
        processing=SectionView("Pending Meeting Tasks (0)", rows=()),
        corrections=SectionView("Correct Speakers (0)", rows=()),
        recovered=SectionView("Interrupted Recordings", rows=()),
        readiness=(
            RowView("Calendar: connected", enabled=False, tooltip="Google Calendar linked"),
        ),
        configuration=(RowView("Notes Customization...", tooltip="Edit the notes template"),),
        diagnostics=(RowView("Check Setup & Dependencies", tooltip="Run diagnostics"),),
        open_meetings_folder=RowView("Open Meetings Folder", tooltip="Open in Finder"),
        quit=RowView("Quit"),
    )

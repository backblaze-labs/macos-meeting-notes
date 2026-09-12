"""Shared test doubles for SidebarWiring-level tests: a `SidebarPanel`
stand-in plus view-tree helpers. Imported by test_sidebar_tray_wiring.py
and test_tray.py (split out to keep both under the 300-line cap)."""

from __future__ import annotations

from appkit_fakes import FakeAppKit

from meeting_memory.ui.sidebar_geometry import Orientation, SnapAnchor


class FakePanel:
    def __init__(self, appkit=None, on_anchor_changed=None):
        self.toggle_calls = 0
        self.is_visible = False
        self.show_calls = 0
        self.hide_calls = 0
        self.appkit = appkit if appkit is not None else FakeAppKit()
        self.content_view = None
        self.on_anchor_changed = on_anchor_changed
        self.orientation = Orientation.VERTICAL
        self.anchor = SnapAnchor.LEFT

    def toggle(self) -> bool:
        self.toggle_calls += 1
        self.is_visible = not self.is_visible
        return self.is_visible

    def show(self) -> None:
        self.show_calls += 1
        self.is_visible = True

    def hide(self) -> None:
        self.hide_calls += 1
        self.is_visible = False

    def set_content_view(self, view) -> None:
        self.content_view = view

    def max_content_height(self) -> float | None:
        return None

    def drag_to(self, anchor: SnapAnchor, orientation: Orientation) -> None:
        """Test helper: mimic SidebarPanel firing on_anchor_changed after a
        drag release, per plan 02 (fires once per real anchor change)."""

        self.anchor = anchor
        self.orientation = orientation
        if self.on_anchor_changed is not None:
            self.on_anchor_changed(anchor)


class _FakeRecorder:
    def __init__(self, is_recording: bool) -> None:
        self.is_recording = is_recording
        self.recording_warning: str | None = None


class _FakeController:
    def __init__(self, *, is_recording: bool = False, duration: int = 0) -> None:
        self.recorder = _FakeRecorder(is_recording)
        self._duration = duration

    def recording_duration_seconds(self) -> int:
        return self._duration


def _all_containers(view):
    yield view
    for sub in getattr(view, "subviews", ()):
        yield from _all_containers(sub)


def _label_text(container) -> str | None:
    subviews = getattr(container, "subviews", None)
    if not subviews:
        return None
    return getattr(subviews[0], "text", None)

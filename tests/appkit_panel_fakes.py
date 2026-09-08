"""Fake `NSPanel` for the sidebar panel tests.

Split out of `appkit_fakes.py` to keep that file under the 300-line cap
`test_structure.py` enforces on everything else (same pattern as
`appkit_widget_fakes.py`). Import it from `appkit_fakes` as before.
"""

from __future__ import annotations

from typing import Any

from appkit_geometry_fakes import FakePoint, FakeRect


class FakeAnimator:
    """`panel.animator()` proxy: applies the frame to the panel immediately."""

    def __init__(self, panel: FakePanel) -> None:
        self._panel = panel

    def setFrame_display_(self, frame: FakeRect, display: bool) -> None:
        self._panel.setFrame_display_(frame, display)


class FakeAnimationContext:
    """`NSAnimationContext` stand-in: runs the group's block synchronously and
    records that an animation ran (the reduce-motion path must skip it)."""

    ran = False
    duration: float | None = None

    @classmethod
    def runAnimationGroup_completionHandler_(cls, block: Any, completion: Any) -> None:
        cls.ran = True
        block(cls())
        if completion is not None:
            completion()

    def setDuration_(self, duration: float) -> None:
        FakeAnimationContext.duration = duration


class FakePanel:
    def __init__(self, frame: FakeRect) -> None:
        self._frame = frame
        self.content_view: Any = None
        self.autosave_name: str | None = None
        self.sharing_type: Any = None
        self.made_key_and_ordered_front_called = False
        self.order_front_regardless_called = False
        self.order_out_called = False
        self.frame_calls: list[tuple] = []

    @classmethod
    def alloc(cls) -> FakePanel:
        return cls.__new__(cls)

    def initWithContentRect_styleMask_backing_defer_(self, rect, style_mask, backing, defer):
        del style_mask, backing, defer
        FakePanel.__init__(self, rect)
        return self

    def setFloatingPanel_(self, value: bool) -> None:
        self.floating = value

    def setLevel_(self, level: Any) -> None:
        self.level = level

    def setCollectionBehavior_(self, behavior: Any) -> None:
        self.collection_behavior = behavior

    def setBackgroundColor_(self, color: Any) -> None:
        self.background_color = color

    def setOpaque_(self, value: bool) -> None:
        self.opaque = value

    def setHasShadow_(self, value: bool) -> None:
        self.has_shadow = value

    def setReleasedWhenClosed_(self, value: bool) -> None:
        self.released_when_closed = value

    def setSharingType_(self, value: Any) -> None:
        self.sharing_type = value

    def setContentView_(self, view: Any) -> None:
        self.content_view = view

    def setFrameAutosaveName_(self, name: str) -> None:
        self.autosave_name = name

    def frame(self) -> FakeRect:
        return self._frame

    def setFrameOrigin_(self, point: FakePoint) -> None:
        self._frame = FakeRect(point, self._frame.size)
        self.frame_calls.append(("setFrameOrigin_", point))

    def setFrame_display_(self, frame: FakeRect, display: bool) -> None:
        del display
        self._frame = frame
        self.frame_calls.append(("setFrame_display_", frame))

    def animator(self) -> FakeAnimator:
        self.frame_calls.append(("animator", None))
        return FakeAnimator(self)

    def orderFrontRegardless(self) -> None:
        self.order_front_regardless_called = True

    def orderOut_(self, sender) -> None:
        del sender
        self.order_out_called = True

    def makeKeyAndOrderFront_(self, sender) -> None:
        del sender
        self.made_key_and_ordered_front_called = True

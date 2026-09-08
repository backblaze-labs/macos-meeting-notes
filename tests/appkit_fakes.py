"""Shared fake AppKit surface for sidebar panel tests.

Mirrors the tiny slice of AppKit/Foundation that `sidebar_panel.py` and
`sidebar_drag.py` touch, following `tray_fakes.py`'s convention of faking
just enough of a third-party API to drive real code without the real
framework (unavailable/unnecessary in CI).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from appkit_geometry_fakes import FakePoint, FakeRect, fake_make_point, fake_make_rect
from appkit_panel_fakes import FakeAnimationContext, FakePanel
from appkit_widget_fakes import (
    FakeNSColor,
    FakeNSFont,
    FakeNSImage,
    FakeNSImageSymbolConfiguration,
    FakeNSImageView,
    FakeNSScrollView,
    FakeNSTextField,
    FakeNSView,
)

__all__ = [
    "FakeAnimationContext",
    "FakeAppKit",
    "FakeNSColor",
    "FakeNSScrollView",
    "FakeNSTextField",
    "FakeNSView",
    "FakeNSWorkspace",
    "FakePoint",
    "FakeRect",
    "FakeScreen",
    "fake_make_point",
    "fake_make_rect",
    "reset_fake_appkit_state",
]


class FakeScreen:
    def __init__(self, visible: FakeRect) -> None:
        self._visible = visible

    def visibleFrame(self) -> FakeRect:
        return self._visible


class FakeNSScreen:
    screens_list: list[FakeScreen] = []

    @classmethod
    def screens(cls) -> list[FakeScreen]:
        return cls.screens_list


class FakeNSEvent:
    location = FakePoint(0.0, 0.0)

    @classmethod
    def mouseLocation(cls) -> FakePoint:
        return cls.location


class FakeNSWorkspace:
    reduce_motion = False

    @classmethod
    def sharedWorkspace(cls) -> FakeNSWorkspace:
        return cls()

    def accessibilityDisplayShouldReduceMotion(self) -> bool:
        return FakeNSWorkspace.reduce_motion


class FakeNSUserDefaults:
    _store: dict[str, str] = {}

    @classmethod
    def standardUserDefaults(cls) -> FakeNSUserDefaults:
        return cls()

    def setObject_forKey_(self, value: Any, key: str) -> None:
        FakeNSUserDefaults._store[key] = value

    def stringForKey_(self, key: str) -> str | None:
        return FakeNSUserDefaults._store.get(key)

    def arrayForKey_(self, key: str) -> list[Any] | None:
        return FakeNSUserDefaults._store.get(key)

    def boolForKey_(self, key: str) -> bool:
        return bool(FakeNSUserDefaults._store.get(key, False))

    def setBool_forKey_(self, value: bool, key: str) -> None:
        FakeNSUserDefaults._store[key] = value


class FakeNSNotificationCenter:
    _observers: dict[Any, Callable] = {}
    _next_token = 0

    @classmethod
    def defaultCenter(cls) -> FakeNSNotificationCenter:
        return cls()

    def addObserverForName_object_queue_usingBlock_(self, name, obj, queue, block) -> Any:
        del name, obj, queue
        FakeNSNotificationCenter._next_token += 1
        token = FakeNSNotificationCenter._next_token
        FakeNSNotificationCenter._observers[token] = block
        return token

    def removeObserver_(self, token: Any) -> None:
        FakeNSNotificationCenter._observers.pop(token, None)


class FakeLayer:
    def __init__(self) -> None:
        self.corner_radius = 0.0
        self.masks_to_bounds = False

    def setCornerRadius_(self, radius: float) -> None:
        self.corner_radius = radius

    def setMasksToBounds_(self, value: bool) -> None:
        self.masks_to_bounds = value


class FakeNSVisualEffectView:
    def __init__(self) -> None:
        self.material: Any = None
        self.blending_mode: Any = None
        self.state: Any = None
        self.subviews: list[Any] = []
        self._window: Any = None
        self._superview: Any = None
        self._frame = fake_make_rect(0.0, 0.0, 0.0, 0.0)

    @classmethod
    def alloc(cls) -> FakeNSVisualEffectView:
        return cls.__new__(cls)

    def init(self) -> FakeNSVisualEffectView:
        FakeNSVisualEffectView.__init__(self)
        return self

    def setMaterial_(self, material: Any) -> None:
        self.material = material

    def setBlendingMode_(self, mode: Any) -> None:
        self.blending_mode = mode

    def setState_(self, state: Any) -> None:
        self.state = state

    def setWantsLayer_(self, value: bool) -> None:
        self.wants_layer = value

    def layer(self) -> FakeLayer:
        if not hasattr(self, "_layer"):
            self._layer = FakeLayer()
        return self._layer

    def addSubview_(self, view: Any) -> None:
        self.subviews.append(view)
        view._superview = self

    def removeFromSuperview(self) -> None:
        superview = self._superview
        if superview is not None and self in superview.subviews:
            superview.subviews.remove(self)
        self._superview = None

    def frame(self) -> FakeRect:
        return self._frame

    def window(self) -> Any:
        return self._window


@dataclass
class FakeAppKit:
    NSPanel: type = FakePanel
    NSVisualEffectView: type = FakeNSVisualEffectView
    NSScreen: type = FakeNSScreen
    NSEvent: type = FakeNSEvent
    NSWorkspace: type = FakeNSWorkspace
    NSAnimationContext: type = FakeAnimationContext
    NSNotificationCenter: type = FakeNSNotificationCenter
    NSUserDefaults: type = FakeNSUserDefaults
    NSMakeRect: Callable = field(default=fake_make_rect)
    NSMakePoint: Callable = field(default=fake_make_point)
    NSWindowStyleMaskBorderless: int = 1 << 0
    NSWindowStyleMaskNonactivatingPanel: int = 1 << 1
    NSBackingStoreBuffered: int = 2
    NSFloatingWindowLevel: int = 3
    NSWindowCollectionBehaviorCanJoinAllSpaces: int = 1 << 0
    NSWindowCollectionBehaviorFullScreenAuxiliary: int = 1 << 1
    NSWindowSharingNone: int = 0
    NSVisualEffectMaterialHUDWindow: int = 13
    NSVisualEffectBlendingModeBehindWindow: int = 0
    NSVisualEffectStateActive: int = 1
    NSApplicationDidChangeScreenParametersNotification: str = (
        "NSApplicationDidChangeScreenParametersNotification"
    )
    NSView: type = FakeNSView
    NSTextField: type = FakeNSTextField
    NSColor: type = FakeNSColor
    NSScrollView: type = FakeNSScrollView
    NSLineBreakByTruncatingTail: int = 4
    NSFont: type = FakeNSFont
    NSFontWeightSemibold: float = 0.3
    NSFontWeightRegular: float = 0.0
    NSImage: type = FakeNSImage
    NSImageView: type = FakeNSImageView
    NSImageSymbolConfiguration: type = FakeNSImageSymbolConfiguration
    NSImageScaleProportionallyDown: int = 1


def reset_fake_appkit_state() -> None:
    """Call between tests: the fakes above use class-level singletons."""

    FakeNSUserDefaults._store = {}
    FakeNSNotificationCenter._observers = {}
    FakeNSNotificationCenter._next_token = 0
    FakeNSScreen.screens_list = []
    FakeNSWorkspace.reduce_motion = False
    FakeAnimationContext.ran = False
    FakeNSImage.available = True

"""Fake AppKit view/label/color/scroll surface for the vertical-layout widgets
(plan 05: sidebar_widgets.py, sidebar_vertical.py).

Split out of `appkit_fakes.py` to keep that file under the 300-line cap
`test_structure.py` enforces on everything else — see `structure_ui_files.py`
and `structure_d2_files.py` for the same pattern applied to source files.
"""

from __future__ import annotations

from typing import Any

from appkit_geometry_fakes import FakeRect, fake_make_rect


class FakeNSView:
    """Generic view. Row/section builders subclass this dynamically (the
    same pattern `sidebar_drag.py` uses) to get a per-instance `mouseUp_`
    closing over that row's callback, without one Objective-C class per row."""

    def __init__(self, frame: FakeRect | None = None) -> None:
        self._frame = frame or fake_make_rect(0.0, 0.0, 0.0, 0.0)
        self.subviews: list[Any] = []
        self.tooltip: str | None = None
        self._window: Any = None
        self._superview: Any = None

    @classmethod
    def alloc(cls) -> FakeNSView:
        return cls.__new__(cls)

    def initWithFrame_(self, frame: FakeRect) -> FakeNSView:
        FakeNSView.__init__(self, frame)
        return self

    def frame(self) -> FakeRect:
        return self._frame

    def setFrameOrigin_(self, point: Any) -> None:
        from appkit_geometry_fakes import FakeRect as _FakeRect

        self._frame = _FakeRect(point, self._frame.size)

    def addSubview_(self, view: Any) -> None:
        self.subviews.append(view)
        view._superview = self

    def removeFromSuperview(self) -> None:
        superview = self._superview
        if superview is not None and self in superview.subviews:
            superview.subviews.remove(self)
        self._superview = None

    def setToolTip_(self, tooltip: str | None) -> None:
        self.tooltip = tooltip

    def setFrame_(self, frame: FakeRect) -> None:
        self._frame = frame

    def bounds(self) -> FakeRect:
        return self._frame

    def window(self) -> Any:
        return self._window


class FakeNSTextField:
    def __init__(self) -> None:
        self._superview: Any = None
        self.text = ""
        self.text_color: Any = None
        self.line_break_mode: Any = None
        self._frame = fake_make_rect(0.0, 0.0, 0.0, 0.0)

    @classmethod
    def labelWithString_(cls, text: str) -> FakeNSTextField:
        field = cls()
        field.text = text
        return field

    def setFrame_(self, frame: FakeRect) -> None:
        self._frame = frame

    def frame(self) -> FakeRect:
        return self._frame

    def setStringValue_(self, text: str) -> None:
        self.text = text

    def stringValue(self) -> str:
        return self.text

    def setTextColor_(self, color: Any) -> None:
        self.text_color = color

    def setLineBreakMode_(self, mode: Any) -> None:
        self.line_break_mode = mode

    def setFont_(self, font: Any) -> None:
        self.font = font

    def setAlignment_(self, alignment: Any) -> None:
        self.alignment = alignment

    def removeFromSuperview(self) -> None:
        superview = self._superview
        if superview is not None and self in superview.subviews:
            superview.subviews.remove(self)
        self._superview = None

    def setToolTip_(self, tooltip: str | None) -> None:
        self.tooltip = tooltip

    def setHidden_(self, hidden: bool) -> None:
        self.hidden = hidden

    def isHidden(self) -> bool:
        return getattr(self, "hidden", False)


class FakeNSImage:
    """Stands in for an SF Symbol image; `name` is the symbol name."""

    available = True  # tests flip this to simulate pre-Big Sur AppKit

    def __init__(self, name: str) -> None:
        self.name = name
        self.point_size: float | None = None

    @classmethod
    def imageWithSystemSymbolName_accessibilityDescription_(cls, name, description):
        del description
        return cls(name) if cls.available else None

    def imageWithSymbolConfiguration_(self, configuration: Any) -> FakeNSImage:
        image = FakeNSImage(self.name)
        image.point_size = configuration.point_size
        return image


class FakeNSImageSymbolConfiguration:
    def __init__(self, point_size: float, weight: Any) -> None:
        self.point_size = point_size
        self.weight = weight

    @classmethod
    def configurationWithPointSize_weight_(cls, point_size, weight):
        return cls(point_size, weight)


class FakeNSImageView(FakeNSView):
    def __init__(self, frame: FakeRect | None = None) -> None:
        super().__init__(frame)
        self.image: Any = None
        self.tint: Any = None
        self.scaling: Any = None

    def initWithFrame_(self, frame: FakeRect) -> FakeNSImageView:
        FakeNSImageView.__init__(self, frame)
        return self

    def setImage_(self, image: Any) -> None:
        self.image = image

    def setContentTintColor_(self, color: Any) -> None:
        self.tint = color

    def setImageScaling_(self, scaling: Any) -> None:
        self.scaling = scaling


class FakeNSColor:
    @classmethod
    def labelColor(cls) -> str:
        return "label"

    @classmethod
    def secondaryLabelColor(cls) -> str:
        return "secondaryLabel"

    @classmethod
    def systemOrangeColor(cls) -> str:
        return "systemOrange"

    @classmethod
    def systemRedColor(cls) -> str:
        return "systemRed"

    @classmethod
    def controlAccentColor(cls) -> str:
        return "controlAccent"

    @classmethod
    def colorWithSRGBRed_green_blue_alpha_(cls, r: float, g: float, b: float, a: float) -> str:
        return f"srgb({r:.2f},{g:.2f},{b:.2f},{a:.2f})"


class FakeNSFont:
    @classmethod
    def boldSystemFontOfSize_(cls, size: float) -> str:
        return f"bold:{size}"

    @classmethod
    def systemFontOfSize_weight_(cls, size: float, weight: Any) -> str:
        return f"system:{size}:{weight}"

    @classmethod
    def monospacedDigitSystemFontOfSize_weight_(cls, size: float, weight: Any) -> str:
        return f"monospaced:{size}:{weight}"


class FakeNSScrollView(FakeNSView):
    def __init__(self, frame: FakeRect | None = None) -> None:
        super().__init__(frame)
        self.document_view: Any = None
        self.has_vertical_scroller = False
        self.has_horizontal_scroller = False

    @classmethod
    def alloc(cls) -> FakeNSScrollView:
        return cls.__new__(cls)

    def initWithFrame_(self, frame: FakeRect) -> FakeNSScrollView:
        FakeNSScrollView.__init__(self, frame)
        return self

    def setDocumentView_(self, view: Any) -> None:
        self.document_view = view

    def setHasVerticalScroller_(self, value: bool) -> None:
        self.has_vertical_scroller = value

    def setHasHorizontalScroller_(self, value: bool) -> None:
        self.has_horizontal_scroller = value

    def setDrawsBackground_(self, value: bool) -> None:
        self.draws_background = value

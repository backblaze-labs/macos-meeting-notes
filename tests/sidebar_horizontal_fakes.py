"""Fake AppKit surface + view-model fixtures for the horizontal sidebar
layout tests (plan 06: sidebar_horizontal.py).

Kept separate from the shared `appkit_fakes.py`/`appkit_widget_fakes.py`,
which were also being extended concurrently for plan 05 — this avoids
touching either file. Split out of `test_sidebar_horizontal.py` itself for
the same reason `structure_ui_files.py` was split out of `test_structure.py`:
keeping that file under the 300-line cap it enforces on everything else.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from appkit_fakes import FakeNSUserDefaults
from appkit_geometry_fakes import fake_make_rect
from appkit_widget_fakes import FakeNSColor, FakeNSFont, FakeNSTextField, FakeNSView


class HFakeNSView(FakeNSView):
    hidden = False

    def setFrame_(self, frame) -> None:
        self._frame = frame

    def setHidden_(self, value: bool) -> None:
        self.hidden = value

    def bounds(self):
        return self._frame


class HFakeNSTextField(FakeNSTextField, HFakeNSView):
    @classmethod
    def labelWithString_(cls, text: str) -> HFakeNSTextField:
        field = cls()
        field._frame = fake_make_rect(0.0, 0.0, 0.0, 0.0)
        field.text = text
        return field


class FakeNSObject:
    @classmethod
    def alloc(cls):
        return cls.__new__(cls)

    def init(self):
        return self


class FakeMenuItem:
    def __init__(self, title: str) -> None:
        self.title = title


class FakeNSPopUpButton(HFakeNSView):
    def __init__(self) -> None:
        super().__init__()
        self.items: list[FakeMenuItem] = []
        self.selected_index = 0
        self.target: Any = None
        self.action: str | None = None

    @classmethod
    def alloc(cls) -> FakeNSPopUpButton:
        return cls.__new__(cls)

    def initWithFrame_pullsDown_(self, frame, pulls_down: bool) -> FakeNSPopUpButton:
        FakeNSPopUpButton.__init__(self)
        self._frame = frame
        del pulls_down
        return self

    def addItemWithTitle_(self, title: str) -> None:
        self.items.append(FakeMenuItem(title))

    def selectItemAtIndex_(self, index: int) -> None:
        self.selected_index = index

    def indexOfSelectedItem(self) -> int:
        return self.selected_index

    def setTarget_(self, target: Any) -> None:
        self.target = target

    def setAction_(self, action: str) -> None:
        self.action = action

    def click(self, index: int) -> None:
        """Test helper: simulate the user picking `index` from the popup."""

        self.selectItemAtIndex_(index)
        getattr(self.target, self.action.replace(":", "_"))(self)


class FakeNSViewController:
    @classmethod
    def alloc(cls) -> FakeNSViewController:
        return cls.__new__(cls)

    def init(self) -> FakeNSViewController:
        self.view = None
        return self

    def setView_(self, view: Any) -> None:
        self.view = view


class FakeNSPopover:
    shown: list[tuple[Any, Any, Any]] = []

    @classmethod
    def alloc(cls) -> FakeNSPopover:
        return cls.__new__(cls)

    def init(self) -> FakeNSPopover:
        self.content_view_controller = None
        self.behavior = None
        self.closed = False
        return self

    def setContentViewController_(self, controller: Any) -> None:
        self.content_view_controller = controller

    def setBehavior_(self, behavior: Any) -> None:
        self.behavior = behavior

    def showRelativeToRect_ofView_preferredEdge_(self, rect, view, edge) -> None:
        FakeNSPopover.shown.append((rect, view, edge))

    def close(self) -> None:
        self.closed = True


class FakePanel:
    """Stands in for `SidebarPanel` (not the raw `NSPanel`) — only `.show()`
    is public on the real thing."""

    def __init__(self) -> None:
        self.shown = False

    def show(self) -> None:
        self.shown = True


@dataclass
class HorizontalFakeAppKit:
    NSView: type = HFakeNSView
    NSTextField: type = HFakeNSTextField
    NSColor: type = FakeNSColor
    NSObject: type = FakeNSObject
    NSUserDefaults: type = FakeNSUserDefaults
    NSPopUpButton: type = FakeNSPopUpButton
    NSViewController: type = FakeNSViewController
    NSPopover: type = FakeNSPopover
    NSPopoverBehaviorTransient: int = 2
    NSMaxYEdge: int = 1
    NSMinYEdge: int = 0
    NSLineBreakByTruncatingTail: int = 4
    NSFont: type = FakeNSFont
    NSFontWeightSemibold: float = 0.3
    NSMakeRect: Any = field(default=staticmethod(fake_make_rect))


class Row:
    def __init__(self, label: str, action=None):
        self.label = label
        self.action = action


class RecordingView:
    def __init__(self, label: str, audio_warning: bool = False):
        self.label = label
        self.audio_warning = audio_warning


class FakeSection:
    def __init__(self, rows=()):
        self.rows = rows


class FakeViewModel:
    def __init__(self, *, recording, audio_modes=(), pending_rows=()):
        self.recording = recording
        self.audio_modes = audio_modes
        self.pending = FakeSection(pending_rows)

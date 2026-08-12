"""Small AppKit fakes shared by speaker-review UI tests."""

from __future__ import annotations

import types


class FakeAppKit(types.SimpleNamespace):
    def __init__(self, responses: list[int]) -> None:
        self.alerts: list[FakeAlert] = []
        super().__init__(
            NSAlert=_FakeAlertFactory(responses, self.alerts),
            NSFont=types.SimpleNamespace(systemFontOfSize_=lambda _size: object()),
            NSMakePoint=lambda *args: args,
            NSMakeRect=lambda *args: args,
            NSPopUpButton=FakePopUpButton,
            NSScrollView=FakeScrollView,
            NSTextField=FakeTextField,
            NSView=FakeView,
        )


class _FakeAlloc:
    @classmethod
    def alloc(cls):
        return cls()


class _FakeAlertFactory:
    def __init__(self, responses: list[int], alerts: list[FakeAlert]) -> None:
        self.responses = responses
        self.alerts = alerts

    def alloc(self):
        alert = FakeAlert(self.responses)
        self.alerts.append(alert)
        return alert


class FakeAlert:
    def __init__(self, responses: list[int]) -> None:
        self.responses = responses
        self.accessory = None
        self.buttons: list[str] = []

    def init(self):
        return self

    def setMessageText_(self, _text) -> None:
        pass

    def setInformativeText_(self, _text) -> None:
        pass

    def addButtonWithTitle_(self, title) -> None:
        self.buttons.append(title)

    def setAccessoryView_(self, view) -> None:
        self.accessory = view

    def runModal(self) -> int:
        return self.responses.pop(0)


class FakeView(_FakeAlloc):
    def initWithFrame_(self, frame):
        self.frame = frame
        return self

    def addSubview_(self, _view) -> None:
        pass


class FakeScrollView(_FakeAlloc):
    def initWithFrame_(self, frame):
        self.frame = frame
        return self

    def setDocumentView_(self, view) -> None:
        self.document_view = view

    def setHasVerticalScroller_(self, value) -> None:
        self.vertical_scroller = value

    def setHasHorizontalScroller_(self, value) -> None:
        self.horizontal_scroller = value

    def setAutohidesScrollers_(self, _value) -> None:
        pass

    def contentView(self):
        return self

    def scrollToPoint_(self, point) -> None:
        self.scrolled_to = point

    def reflectScrolledClipView_(self, _view) -> None:
        pass


class FakePopUpButton(_FakeAlloc):
    def initWithFrame_pullsDown_(self, _frame, _pulls_down):
        self.selected = ""
        return self

    def addItemsWithTitles_(self, options) -> None:
        self.selected = options[0]

    def selectItemWithTitle_(self, option) -> None:
        self.selected = option

    def titleOfSelectedItem(self) -> str:
        return self.selected


class FakeTextField(_FakeAlloc):
    def initWithFrame_(self, _frame):
        self.value = ""
        return self

    def setStringValue_(self, value) -> None:
        self.value = value

    def stringValue(self) -> str:
        return self.value

    def setPlaceholderString_(self, _value) -> None:
        pass

    def setBezeled_(self, _value) -> None:
        pass

    def setDrawsBackground_(self, _value) -> None:
        pass

    def setEditable_(self, _value) -> None:
        pass

    def setSelectable_(self, _value) -> None:
        pass

    def setFont_(self, _value) -> None:
        pass

"""Standard nonmodal macOS controls for local model preparation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from meeting_memory.ui.modal_focus import activate_app

_TARGET_CLASS = None


@dataclass
class LocalModelPanel:
    window: Any
    summary: Any
    details: Any
    indicator: Any
    prepare: Any
    cancel: Any
    target: Any

    def show(self):
        activate_app()
        self.window.makeKeyAndOrderFront_(None)

    def update(self, *, summary, details, busy, prepare_enabled, retry, fraction):
        self.summary.setStringValue_(summary)
        self.details.setStringValue_(details)
        self.prepare.setTitle_("Retry" if retry else "Prepare Local Models")
        self.prepare.setEnabled_(prepare_enabled and not busy)
        self.cancel.setEnabled_(busy)
        self.indicator.setIndeterminate_(fraction is None)
        if fraction is not None:
            self.indicator.setDoubleValue_(fraction * 100)
        if busy:
            self.indicator.startAnimation_(None)
        else:
            self.indicator.stopAnimation_(None)


def create_model_panel(on_prepare, on_cancel):
    from AppKit import (
        NSBackingStoreBuffered,
        NSButton,
        NSMakeRect,
        NSPanel,
        NSProgressIndicator,
        NSWindowStyleMaskClosable,
        NSWindowStyleMaskTitled,
    )

    from meeting_memory.ui.configuration_forms import _label

    window = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(0, 0, 640, 310),
        NSWindowStyleMaskTitled | NSWindowStyleMaskClosable,
        NSBackingStoreBuffered,
        False,
    )
    window.setTitle_("Local Transcription Models")
    window.setReleasedWhenClosed_(False)
    window.center()
    content = window.contentView()
    summary = _label("Checking local models.", 22, 245, 595, 44)
    details = _label("", 22, 163, 595, 76)
    for label in (summary, details):
        label.cell().setWraps_(True)
        label.cell().setScrollable_(False)
    details.setSelectable_(True)
    disclosure = _label(
        "Preparation downloads model weights from Hugging Face without meeting content. "
        "It does not process pending recordings. Use the separate Retry Pending or Failed "
        "Transcriptions action when ready.",
        22,
        65,
        595,
        65,
    )
    disclosure.cell().setWraps_(True)
    disclosure.cell().setScrollable_(False)
    indicator = NSProgressIndicator.alloc().initWithFrame_(NSMakeRect(22, 140, 595, 16))
    indicator.setMinValue_(0)
    indicator.setMaxValue_(100)
    prepare = NSButton.alloc().initWithFrame_(NSMakeRect(325, 18, 195, 32))
    prepare.setTitle_("Prepare Local Models")
    prepare.setBezelStyle_(1)
    cancel = NSButton.alloc().initWithFrame_(NSMakeRect(525, 18, 95, 32))
    cancel.setTitle_("Cancel")
    cancel.setBezelStyle_(1)
    target = _target_class().alloc().init()
    target.on_prepare = on_prepare
    target.on_cancel = on_cancel
    for control, action in ((prepare, "prepare:"), (cancel, "cancel:")):
        control.setTarget_(target)
        control.setAction_(action)
    for control in (summary, details, disclosure, indicator, prepare, cancel):
        content.addSubview_(control)
    return LocalModelPanel(window, summary, details, indicator, prepare, cancel, target)


def _target_class():
    global _TARGET_CLASS
    if _TARGET_CLASS is None:
        from Foundation import NSObject

        class LocalModelPanelTarget(NSObject):
            def prepare_(self, _sender):
                self.on_prepare()

            def cancel_(self, _sender):
                self.on_cancel()

        _TARGET_CLASS = LocalModelPanelTarget
    return _TARGET_CLASS

"""The real AppKit namespace the sidebar modules resolve against.

Every sidebar module takes an injected `appkit` namespace (a fake in tests,
this in production) so the panel, drag view, and both layouts never import
`AppKit` themselves. Each symbol any of them touches must be listed here —
a missing one only surfaces at runtime, on the code path that uses it (the
horizontal layout's popup and popover were found this way during plan 06's
manual pass).
"""

from __future__ import annotations

from typing import Any


def real_appkit() -> Any:
    import AppKit
    import Foundation

    class _RealAppKit:
        # Panel shell + drag view (plan 02)
        NSPanel = AppKit.NSPanel
        NSVisualEffectView = AppKit.NSVisualEffectView
        NSScreen = AppKit.NSScreen
        NSEvent = AppKit.NSEvent
        NSWorkspace = AppKit.NSWorkspace
        NSAnimationContext = AppKit.NSAnimationContext
        NSNotificationCenter = Foundation.NSNotificationCenter
        NSUserDefaults = Foundation.NSUserDefaults
        NSMakeRect = staticmethod(Foundation.NSMakeRect)
        NSMakePoint = staticmethod(Foundation.NSMakePoint)
        NSWindowStyleMaskBorderless = AppKit.NSWindowStyleMaskBorderless
        NSWindowStyleMaskNonactivatingPanel = AppKit.NSWindowStyleMaskNonactivatingPanel
        NSBackingStoreBuffered = AppKit.NSBackingStoreBuffered
        NSFloatingWindowLevel = AppKit.NSFloatingWindowLevel
        NSWindowCollectionBehaviorCanJoinAllSpaces = (
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
        )
        NSWindowCollectionBehaviorFullScreenAuxiliary = (
            AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
        )
        NSWindowSharingNone = AppKit.NSWindowSharingNone
        NSVisualEffectMaterialHUDWindow = AppKit.NSVisualEffectMaterialHUDWindow
        NSVisualEffectBlendingModeBehindWindow = AppKit.NSVisualEffectBlendingModeBehindWindow
        NSVisualEffectStateActive = AppKit.NSVisualEffectStateActive
        NSApplicationDidChangeScreenParametersNotification = (
            AppKit.NSApplicationDidChangeScreenParametersNotification
        )
        # Content views: sidebar_widgets.py / sidebar_compact.py
        NSView = AppKit.NSView
        NSTextField = AppKit.NSTextField
        NSColor = AppKit.NSColor
        NSScrollView = AppKit.NSScrollView
        NSLineBreakByTruncatingTail = AppKit.NSLineBreakByTruncatingTail
        # Compact icon buttons: sidebar_compact.py
        NSImage = AppKit.NSImage
        NSImageView = AppKit.NSImageView
        NSImageSymbolConfiguration = AppKit.NSImageSymbolConfiguration
        NSImageScaleProportionallyDown = AppKit.NSImageScaleProportionallyDown
        NSFontWeightRegular = AppKit.NSFontWeightRegular
        # Theme: sidebar_theme.py
        NSFont = AppKit.NSFont
        NSFontWeightSemibold = AppKit.NSFontWeightSemibold
        NSGradient = AppKit.NSGradient
        NSBezierPath = AppKit.NSBezierPath

    return _RealAppKit()

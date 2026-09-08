"""Floating sidebar panel: a borderless, non-activating `NSPanel` shell.

Carries no content of its own — `sidebar_tray_wiring.py` calls `set_content_view`. This
module owns the window mechanics only: show/hide, drag-to-snap, orientation
swap, position/anchor persistence, and re-clamping on screen changes.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from meeting_memory.ui.sidebar_appkit import real_appkit as _real_appkit
from meeting_memory.ui.sidebar_drag import (
    make_drag_handle_view,
    make_drag_indicator,
    make_drag_strip,
    position_drag_indicator,
)
from meeting_memory.ui.sidebar_geometry import (
    Orientation,
    Rect,
    SnapAnchor,
    clamp_to_visible,
    orientation_for,
    resolve_drop,
    screen_for,
    snapped_origin,
)

logger = logging.getLogger(__name__)

DEFAULT_VERTICAL = (44.0, 130.0)
DEFAULT_HORIZONTAL = (140.0, 44.0)
AUTOSAVE_NAME = "MeetingMemorySidebar"
ANCHOR_DEFAULTS_KEY = "MeetingMemorySidebarAnchor"
SNAP_ANIMATION_DURATION = 0.18
# Slim strip at the top of the vertical panel that only accepts drag —
# without it the content view (rows with their own mouseUp_) fully covers
# the drag view, and nothing is grabbable. The horizontal bar has its own
# `⠿` handle already so this reserve is vertical-only.
DRAG_HANDLE_HEIGHT = 14.0


class SidebarPanel:
    def __init__(
        self,
        *,
        appkit: Any | None = None,
        on_anchor_changed: Callable[[SnapAnchor], None] | None = None,
    ) -> None:
        self._appkit = appkit if appkit is not None else _real_appkit()
        self._on_anchor_changed = on_anchor_changed
        self._visible = False
        self._content_view: Any = None

        self._panel = self._build_panel()
        self._drag_view = make_drag_handle_view(self._appkit, on_drag_end=self._handle_drag_end)
        self._panel.setContentView_(self._drag_view)
        self._drag_strip = make_drag_strip(self._appkit)
        self._drag_view.addSubview_(self._drag_strip)
        self._drag_indicator = make_drag_indicator(self._appkit)
        self._drag_view.addSubview_(self._drag_indicator)

        # setFrameAutosaveName_ must come after the initial frame is applied,
        # and it silently no-ops if another window already claimed the name.
        self._panel.setFrameAutosaveName_(AUTOSAVE_NAME)
        self._anchor = self._load_anchor()
        self._orientation = orientation_for(self._anchor)

        notification_center = self._appkit.NSNotificationCenter.defaultCenter()
        self._screen_observer = notification_center.addObserverForName_object_queue_usingBlock_(
            self._appkit.NSApplicationDidChangeScreenParametersNotification,
            None,
            None,
            self._handle_screen_change,
        )

    @property
    def appkit(self) -> Any:
        """The resolved AppKit namespace (real or injected), shared with
        `sidebar_tray_wiring.py` so content builders use the same one."""

        return self._appkit

    @property
    def is_visible(self) -> bool:
        return self._visible

    @property
    def anchor(self) -> SnapAnchor:
        return self._anchor

    @property
    def orientation(self) -> Orientation:
        return self._orientation

    def show(self) -> None:
        # orderFrontRegardless, never makeKeyAndOrderFront_ — the latter
        # activates the app and trips the Dock-hiding hook in ui/macos.py.
        self._panel.orderFrontRegardless()
        self._visible = True

    def hide(self) -> None:
        self._panel.orderOut_(None)
        self._visible = False

    def toggle(self) -> bool:
        if self._visible:
            self.hide()
        else:
            self.show()
        return self._visible

    def set_content_view(self, view: Any) -> None:
        """Replace (not stack — plans 05/06 call this on every rebuild) the
        panel's content and resize to fit it. The vertical layout gets a top
        drag strip reserved (DRAG_HANDLE_HEIGHT); the horizontal bar has its
        own `⠿` handle built in and takes the whole drag view.
        """

        if self._content_view is not None:
            self._content_view.removeFromSuperview()
        self._drag_view.addSubview_(view)
        # Keep the strip chrome above freshly added content.
        self._drag_strip.removeFromSuperview()
        self._drag_view.addSubview_(self._drag_strip)
        self._drag_indicator.removeFromSuperview()
        self._drag_view.addSubview_(self._drag_indicator)
        self._content_view = view
        self._resize_to_content(view)

    def _resize_to_content(self, view: Any) -> None:
        """Height follows the content plus (for vertical) the drag strip on
        top, with the content at y=0 so the strip sits above it. AppKit
        origins are bottom-left, so y is adjusted to keep the panel's visual
        top edge where the user last put it.
        """

        content_height = view.frame().size.height
        if content_height <= 0:
            return
        chrome_height = DRAG_HANDLE_HEIGHT if self._orientation is Orientation.VERTICAL else 0.0
        total_height = content_height + chrome_height
        content_width = view.frame().size.width
        view.setFrameOrigin_(self._appkit.NSMakePoint(0.0, 0.0))
        frame = self._panel.frame()
        y = frame.origin.y + frame.size.height - total_height
        self._panel.setFrame_display_(
            self._appkit.NSMakeRect(frame.origin.x, y, content_width, total_height), True
        )
        position_drag_indicator(
            self._appkit,
            self._drag_indicator,
            self._drag_strip,
            content_width,
            total_height,
            chrome_height,
        )

    def teardown(self) -> None:
        """Remove the screen-change observer. Call once, at quit."""

        self._appkit.NSNotificationCenter.defaultCenter().removeObserver_(self._screen_observer)

    def _handle_drag_end(self) -> None:
        frame = self._panel.frame()
        current_rect = Rect(frame.origin.x, frame.origin.y, frame.size.width, frame.size.height)
        screens = self._screen_rects()

        anchor, x, y, orientation = resolve_drop(current_rect, screens, current_anchor=self._anchor)
        width, height = current_rect.width, current_rect.height
        reorienting = orientation is not self._orientation

        # Anchor first, animate last: `_set_anchor` fires `on_anchor_changed`,
        # whose synchronous rebuild resizes the panel to its new content —
        # an animation already in flight toward a default size would win
        # over that resize and clip the content (found in review).
        self._orientation = orientation
        self._set_anchor(anchor)

        if reorienting:
            # The anchor is decided above, from where the user actually
            # dropped it. Only the origin gets recomputed against the new
            # size — re-deciding the anchor from the resized rect's shifted
            # center would flip it to FREE for a wide/short <-> narrow/tall
            # swap near an edge.
            width, height = self._reoriented_size(orientation, current_rect)
            visible = screen_for(current_rect, screens)
            resized_rect = Rect(current_rect.x, current_rect.y, width, height)
            x, y = snapped_origin(resized_rect, visible, anchor)

        self._animate_to(x, y, width, height)

    def _reoriented_size(self, orientation: Orientation, before: Rect) -> tuple[float, float]:
        """The size to animate to after a swap: whatever the content rebuild
        just made the panel, or the orientation's default when no content
        rebuild happened (no content yet, or no `on_anchor_changed`)."""

        frame = self._panel.frame()
        if (frame.size.width, frame.size.height) != (before.width, before.height):
            return frame.size.width, frame.size.height
        return DEFAULT_HORIZONTAL if orientation is Orientation.HORIZONTAL else DEFAULT_VERTICAL

    def max_content_height(self) -> float:
        """Cap for the vertical content (plan 05: 80% of the visible frame),
        so a long section list scrolls instead of running off the screen."""

        frame = self._panel.frame()
        panel_rect = Rect(frame.origin.x, frame.origin.y, frame.size.width, frame.size.height)
        visible = screen_for(panel_rect, self._screen_rects())
        return 0.8 * visible.height - DRAG_HANDLE_HEIGHT

    def _handle_screen_change(self, notification: Any) -> None:
        del notification
        frame = self._panel.frame()
        panel_rect = Rect(frame.origin.x, frame.origin.y, frame.size.width, frame.size.height)
        screens = self._screen_rects()
        visible = screen_for(panel_rect, screens)
        x, y = clamp_to_visible(panel_rect, visible)
        self._panel.setFrameOrigin_(self._appkit.NSMakePoint(x, y))

    def _animate_to(self, x: float, y: float, width: float, height: float) -> None:
        appkit = self._appkit
        frame = appkit.NSMakeRect(x, y, width, height)

        # Check every snap, not once at init — users change this live.
        if appkit.NSWorkspace.sharedWorkspace().accessibilityDisplayShouldReduceMotion():
            self._panel.setFrame_display_(frame, True)
            return

        def _animate(context: Any) -> None:
            context.setDuration_(SNAP_ANIMATION_DURATION)
            self._panel.animator().setFrame_display_(frame, True)

        appkit.NSAnimationContext.runAnimationGroup_completionHandler_(_animate, None)

    def _set_anchor(self, anchor: SnapAnchor) -> None:
        if anchor == self._anchor:
            return
        self._anchor = anchor
        self._appkit.NSUserDefaults.standardUserDefaults().setObject_forKey_(
            anchor.value, ANCHOR_DEFAULTS_KEY
        )
        if self._on_anchor_changed is not None:
            self._on_anchor_changed(anchor)

    def _load_anchor(self) -> SnapAnchor:
        value = self._appkit.NSUserDefaults.standardUserDefaults().stringForKey_(
            ANCHOR_DEFAULTS_KEY
        )
        try:
            return SnapAnchor(value) if value else SnapAnchor.FREE
        except ValueError:
            return SnapAnchor.FREE

    def _screen_rects(self) -> list[Rect]:
        rects = []
        for screen in self._appkit.NSScreen.screens():
            visible = screen.visibleFrame()
            rects.append(
                Rect(visible.origin.x, visible.origin.y, visible.size.width, visible.size.height)
            )
        return rects

    def _build_panel(self) -> Any:
        appkit = self._appkit
        width, height = DEFAULT_VERTICAL
        style_mask = appkit.NSWindowStyleMaskBorderless | appkit.NSWindowStyleMaskNonactivatingPanel
        panel = appkit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            appkit.NSMakeRect(0.0, 0.0, width, height),
            style_mask,
            appkit.NSBackingStoreBuffered,
            False,
        )
        panel.setFloatingPanel_(True)
        panel.setLevel_(appkit.NSFloatingWindowLevel)
        panel.setCollectionBehavior_(
            appkit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | appkit.NSWindowCollectionBehaviorFullScreenAuxiliary
        )
        panel.setOpaque_(False)
        # Clear, or the window paints its default background outside the
        # content view's rounded mask and the corners show as white edges.
        panel.setBackgroundColor_(appkit.NSColor.clearColor())
        panel.setHasShadow_(True)
        panel.setReleasedWhenClosed_(False)
        # `setSharingType_(NSWindowSharingNone)` used to be set here to hide
        # the panel from `screencapture` / screen shares (plan 00 question 7,
        # plan 02's `NSWindowSharingNone` decision). Removed on request —
        # the panel now appears in shots and shares like any normal window.
        # To bring it back: set the sharing type here and restore the test
        # `test_sharing_type_set_at_construction`.
        return panel

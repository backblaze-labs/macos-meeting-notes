"""Status item becomes a toggle button.

The ONLY module allowed to reach into rumps 0.4.0 internals
(`rumps_app._nsapp.nsstatusitem`). See
docs/features/sidebar/completed/03-status-item-toggle.md.

Right-click detection note (verified empirically on Darwin 25.6.0, see that
plan's findings): the documented approach of arming the button with
`sendActionOn_(LeftMouseUp | RightMouseUp)` and then reading
`NSApp.currentEvent().type()` does NOT work here. The status-item button runs
its own modal tracking loop on mouse-down and swallows the mouse-up, so the
action always sees a synthesized left-mouse-up (type 2) no matter which
button was pressed. Instead we intercept RightMouseDown with a local event
monitor scoped to the status item's own window, handle it, and swallow it so
the button never starts tracking — leaving left-clicks on the ordinary
target/action path.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

LOGGER = logging.getLogger(__name__)


class TogglePanel(Protocol):
    def toggle(self) -> None: ...


class ClickAppKit(Protocol):
    """Seam over the AppKit specifics this module needs, so it is
    unit-testable without a display."""

    def make_click_target(self, handler: Any) -> Any: ...
    def install_right_click_monitor(self, button: Any, handler: Any) -> Any: ...
    def show_quit_menu(self, status_item: Any, on_quit: Any) -> None: ...
    def ensure_quit_item(self, menu: Any, on_quit: Any) -> None: ...
    def set_recording_indicator(self, button: Any, on: bool) -> None: ...


class SidebarToggle:
    """Owns the status item's click behavior."""

    def __init__(
        self,
        rumps_app: Any,
        panel: TogglePanel,
        *,
        on_quit: Any,
        appkit: ClickAppKit | None = None,
    ) -> None:
        self._rumps_app = rumps_app
        self._panel = panel
        self._on_quit = on_quit
        self._appkit = appkit or _RealClickAppKit()
        self._installed = False
        # Both kept as strong references: pyobjc will not retain them for us.
        self._handler: Any = None
        self._monitor: Any = None
        self._indicator_on = False

    def install(self) -> bool:
        """Detach the rumps menu and arm the status item directly.

        Must run after rumps has launched (`applicationDidFinishLaunching_`
        is what attaches the menu in the first place) — call this from
        `run()` or a first-timer-tick, never from `__init__`.

        Returns True once installed. On failure the rumps menu is restored
        and given a Quit item (the runtime app builds no menu of its own any
        more, so a bare restore would leave an empty, un-quittable menu).
        """

        if self._installed:
            return True
        status_item = self._rumps_app._nsapp.nsstatusitem
        try:
            status_item.setMenu_(None)
            status_item.setTitle_(None)
            button = status_item.button()
            handler = self._appkit.make_click_target(self._handle_left_click)
            button.setTarget_(handler)
            button.setAction_("statusItemClicked:")
            monitor = self._appkit.install_right_click_monitor(button, self._handle_right_click)
        except Exception:
            LOGGER.exception("Could not install sidebar toggle; restoring rumps menu")
            self._restore_menu(status_item)
            return False
        self._handler = handler
        self._monitor = monitor
        self._installed = True
        return True

    def set_recording_indicator(self, on: bool) -> None:
        """A red dot beside the icon while recording — the one piece of state
        the menu bar carries, so a hidden panel never hides the fact that a
        recording is running. No timer: that stays in the panel."""

        if not self._installed or on == self._indicator_on:
            return
        self._indicator_on = on
        self._appkit.set_recording_indicator(self._rumps_app._nsapp.nsstatusitem.button(), on)

    def _handle_left_click(self, sender: Any) -> None:
        self._panel.toggle()

    def _handle_right_click(self) -> None:
        status_item = self._rumps_app._nsapp.nsstatusitem
        self._appkit.show_quit_menu(status_item, self._on_quit)

    def _restore_menu(self, status_item: Any) -> None:
        try:
            menu = self._original_menu()
            self._appkit.ensure_quit_item(menu, self._on_quit)
            status_item.setMenu_(menu)
        except Exception:
            LOGGER.exception("Could not restore rumps menu after a failed toggle install")

    def _original_menu(self) -> Any:
        return self._rumps_app._nsapp._app["_menu"]._menu


_CLICK_TARGET_CLASS: Any = None


def _click_target_class() -> Any:
    """Define the Objective-C target class exactly once.

    pyobjc registers these with the Objective-C runtime by name, so defining
    one per call raises on the second — and an exception raised inside an
    event-monitor block is swallowed rather than surfaced, which makes that
    failure mode invisible.
    """

    global _CLICK_TARGET_CLASS
    if _CLICK_TARGET_CLASS is None:
        from Foundation import NSObject

        class _ClickTarget(NSObject):
            def statusItemClicked_(self, sender: Any) -> None:
                handler = getattr(self, "_meeting_memory_handler", None)
                if handler is not None:
                    handler(sender)

        _CLICK_TARGET_CLASS = _ClickTarget
    return _CLICK_TARGET_CLASS


class _RealClickAppKit:
    """Default `ClickAppKit` backed by real AppKit. Imports are lazy so this
    module still loads on a machine with no AppKit available."""

    def __init__(self) -> None:
        # Strong references: pyobjc will not retain these for us, and a
        # collected menu or target silently stops working.
        self._quit_menu: Any = None
        self._quit_target: Any = None

    def make_click_target(self, handler: Any) -> Any:
        target = _click_target_class().alloc().init()
        # Settable because _ClickTarget is a Python-defined ObjC subclass;
        # the same assignment on a pure ObjC object (NSMenu) would raise.
        target._meeting_memory_handler = handler
        return target

    def install_right_click_monitor(self, button: Any, handler: Any) -> Any:
        from AppKit import NSEvent, NSEventMaskRightMouseDown

        def monitor_handler(event: Any) -> Any:
            # Resolve the button's window at event time, not install time: the
            # status item's window is not yet its final one during the first
            # timer tick, so a window captured at install never matches.
            if event.window() is not button.window():
                return event  # a right-click elsewhere in the app: leave it alone
            handler()
            return None  # swallow, so the button never starts its tracking loop

        return NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
            NSEventMaskRightMouseDown, monitor_handler
        )

    def show_quit_menu(self, status_item: Any, on_quit: Any) -> None:
        if self._quit_menu is None:
            from AppKit import NSMenu

            menu = NSMenu.alloc().init()
            menu.addItem_(self._quit_item(on_quit))
            self._quit_menu = menu
        status_item.popUpStatusItemMenu_(self._quit_menu)

    def ensure_quit_item(self, menu: Any, on_quit: Any) -> None:
        if menu is not None and menu.numberOfItems() == 0:
            menu.addItem_(self._quit_item(on_quit))

    def set_recording_indicator(self, button: Any, on: bool) -> None:
        from AppKit import (
            NSAttributedString,
            NSColor,
            NSFont,
            NSFontAttributeName,
            NSForegroundColorAttributeName,
            NSImageLeft,
        )

        if not on:
            button.setTitle_("")
            return
        dot = NSAttributedString.alloc().initWithString_attributes_(
            " ●",
            {
                NSForegroundColorAttributeName: NSColor.systemRedColor(),
                NSFontAttributeName: NSFont.systemFontOfSize_(10.0),
            },
        )
        button.setImagePosition_(NSImageLeft)
        button.setAttributedTitle_(dot)

    def _quit_item(self, on_quit: Any) -> Any:
        from AppKit import NSMenuItem

        if self._quit_target is None:
            self._quit_target = self.make_click_target(lambda _sender: on_quit())
        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Quit", None, "")
        item.setTarget_(self._quit_target)
        item.setAction_("statusItemClicked:")
        return item

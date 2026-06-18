"""macOS UI helpers used by the tray app."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any


def hide_dock_icon(logger: logging.Logger) -> None:
    """Make the Python-hosted app behave like a menu-bar accessory."""
    try:
        from AppKit import NSApplication, NSApplicationActivationPolicyAccessory

        NSApplication.sharedApplication().setActivationPolicy_(
            NSApplicationActivationPolicyAccessory
        )
    except Exception:
        logger.debug("Could not hide Dock icon", exc_info=True)


def keep_timer_running_during_menu_tracking(timer: Any, logger: logging.Logger) -> None:
    """Let the recording timer keep ticking while the menu is open."""
    try:
        from Foundation import NSEventTrackingRunLoopMode, NSRunLoop, NSRunLoopCommonModes

        ns_timer = timer._nstimer
        run_loop = NSRunLoop.currentRunLoop()
        run_loop.addTimer_forMode_(ns_timer, NSRunLoopCommonModes)
        run_loop.addTimer_forMode_(ns_timer, NSEventTrackingRunLoopMode)
    except Exception:
        logger.debug("Could not add tray timer to menu tracking modes", exc_info=True)


def allow_foreground_notifications(logger: logging.Logger) -> None:
    """Show notifications as banners even when the menu-bar app is active."""
    try:
        from Foundation import NSSelectorFromString
        from rumps.rumps import NSApp

        selector = NSSelectorFromString(
            "userNotificationCenter:shouldPresentNotification:"
        )
        if NSApp.instancesRespondToSelector_(selector):
            return

        def userNotificationCenter_shouldPresentNotification_(
            self,
            notification_center,
            notification,
        ) -> bool:
            del self, notification_center, notification
            return True

        NSApp.userNotificationCenter_shouldPresentNotification_ = (
            userNotificationCenter_shouldPresentNotification_
        )
    except Exception:
        logger.debug("Could not enable foreground notification banners", exc_info=True)


def open_in_finder(path: Path) -> None:
    subprocess.run(["open", str(path)], check=False)


def display_notification(title: str, subtitle: str, message: str, logger: logging.Logger) -> None:
    parts = [
        "display notification",
        _quote_applescript(message),
        "with title",
        _quote_applescript(title),
    ]
    if subtitle:
        parts.extend(["subtitle", _quote_applescript(subtitle)])
    try:
        subprocess.run(["osascript", "-e", " ".join(parts)], check=False, capture_output=True)
    except Exception:
        logger.debug("Could not display fallback notification", exc_info=True)


def _quote_applescript(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

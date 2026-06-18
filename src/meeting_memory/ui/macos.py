"""macOS UI helpers used by the tray app."""

from __future__ import annotations

import logging
import subprocess
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

UN_PRESENTATION_OPTIONS = 2 | 8 | 16
_UN_DELEGATE: Any | None = None
_UN_RESPONSE_HANDLER: Callable[[dict[str, Any]], None] | None = None


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


def configure_modern_notifications(
    handler: Callable[[dict[str, Any]], None],
    logger: logging.Logger,
) -> None:
    """Configure the modern notification center and retain its delegate."""
    global _UN_DELEGATE, _UN_RESPONSE_HANDLER
    try:
        classes = _load_user_notifications()
        delegate_class = _modern_notification_delegate_class()
        _UN_RESPONSE_HANDLER = handler
        _UN_DELEGATE = delegate_class.alloc().init()
        center = classes["UNUserNotificationCenter"].currentNotificationCenter()
        center.setDelegate_(_UN_DELEGATE)
    except Exception:
        logger.debug("Could not configure modern notifications", exc_info=True)


def deliver_modern_notification(
    title: str,
    subtitle: str,
    message: str,
    **kwargs,
) -> None:
    classes = _load_user_notifications()
    center = classes["UNUserNotificationCenter"].currentNotificationCenter()
    content = classes["UNMutableNotificationContent"].alloc().init()
    content.setTitle_(title)
    content.setSubtitle_(subtitle)
    content.setBody_(message)
    if kwargs.get("sound", True):
        content.setSound_(classes["UNNotificationSound"].defaultSound())

    data = _notification_data(kwargs.get("data"))
    if data:
        content.setUserInfo_(data)

    action_button = kwargs.get("action_button")
    if action_button:
        category_id = _set_modern_action_category(center, classes, str(action_button), data)
        content.setCategoryIdentifier_(category_id)

    request = classes["UNNotificationRequest"].requestWithIdentifier_content_trigger_(
        str(uuid.uuid4()),
        content,
        None,
    )
    center.addNotificationRequest_(request)


def deliver_notification(
    rumps_module: Any,
    title: str,
    subtitle: str,
    message: str,
    **kwargs,
) -> None:
    try:
        deliver_modern_notification(title, subtitle, message, **kwargs)
        return
    except Exception:
        pass

    from Foundation import NSMutableDictionary
    from rumps import _internal
    from rumps.notifications import NSUserNotification, _default_user_notification_center

    notification = NSUserNotification.alloc().init()
    notification.setTitle_(title)
    notification.setSubtitle_(subtitle)
    notification.setInformativeText_(message)

    data = kwargs.get("data")
    if data is not None:
        app = getattr(rumps_module.App, "*app_instance", rumps_module.App)
        dumped = app.serializer.dumps(data)
        user_info = NSMutableDictionary.alloc().init()
        user_info.setDictionary_({"value": _internal.string_to_objc(dumped)})
        notification.setUserInfo_(user_info)

    if kwargs.get("sound", True):
        notification.setSoundName_("NSUserNotificationDefaultSoundName")
    if action_button := kwargs.get("action_button"):
        notification.setActionButtonTitle_(action_button)
        notification.set_showsButtons_(True)
    if other_button := kwargs.get("other_button"):
        notification.setOtherButtonTitle_(other_button)
        notification.set_showsButtons_(True)
    if kwargs.get("has_reply_button"):
        notification.setHasReplyButton_(True)
    if icon := kwargs.get("icon"):
        notification.set_identityImage_(rumps_module._nsimage_from_file(icon))
    if kwargs.get("ignoreDnD"):
        notification.set_ignoresDoNotDisturb_(True)

    _default_user_notification_center().deliverNotification_(notification)


def _load_user_notifications() -> dict[str, Any]:
    import objc

    namespace: dict[str, Any] = {}
    objc.loadBundle(
        "UserNotifications",
        namespace,
        bundle_path="/System/Library/Frameworks/UserNotifications.framework",
    )
    return namespace


def _modern_notification_delegate_class():
    from Foundation import NSObject

    class ModernNotificationDelegate(NSObject):
        def userNotificationCenter_willPresentNotification_withCompletionHandler_(
            self,
            center,
            notification,
            completion_handler,
        ) -> None:
            del self, center, notification
            completion_handler(UN_PRESENTATION_OPTIONS)

        def userNotificationCenter_didReceiveNotificationResponse_withCompletionHandler_(
            self,
            center,
            response,
            completion_handler,
        ) -> None:
            del self, center
            try:
                user_info = response.notification().request().content().userInfo()
                data = dict(user_info) if user_info is not None else {}
                handler = _UN_RESPONSE_HANDLER
                if handler is not None:
                    handler(data)
            finally:
                completion_handler()

    return ModernNotificationDelegate


def _notification_data(data: object) -> dict[str, Any]:
    if isinstance(data, dict):
        return {str(key): value for key, value in data.items() if value is not None}
    return {}


def _set_modern_action_category(
    center: Any,
    classes: dict[str, Any],
    action_button: str,
    data: dict[str, Any],
) -> str:
    action_id = str(data.get("action") or "default")
    category_id = f"meeting-memory-{action_id}"
    action = classes["UNNotificationAction"].actionWithIdentifier_title_options_(
        action_id,
        action_button,
        0,
    )
    category_factory = classes[
        "UNNotificationCategory"
    ].categoryWithIdentifier_actions_intentIdentifiers_options_
    category = category_factory(category_id, [action], [], 0)
    center.setNotificationCategories_({category})
    return category_id


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

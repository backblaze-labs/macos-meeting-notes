"""Notification delivery helpers."""

from __future__ import annotations

import logging
from typing import Any

from meeting_memory.ui.macos import deliver_notification, display_notification


def send_notification(
    rumps_module: Any,
    title: str,
    subtitle: str,
    message: str,
    logger: logging.Logger,
    **kwargs,
) -> None:
    kwargs.setdefault("ignoreDnD", True)
    try:
        if getattr(rumps_module, "__name__", "") == "rumps":
            deliver_notification(rumps_module, title, subtitle, message, **kwargs)
        else:
            rumps_module.notification(title, subtitle, message, **kwargs)
    except Exception:
        logger.exception("Failed to send notification through rumps")
        display_notification(title, subtitle, message, logger)

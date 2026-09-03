"""Keep modal windows in front of the window the user is looking at."""

from __future__ import annotations

import logging
from typing import Any

LOGGER = logging.getLogger(__name__)


def activate_app() -> None:
    """Raise this accessory app so a modal opens in front instead of behind."""
    try:
        from AppKit import NSApplication

        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    except Exception:
        LOGGER.debug("Could not activate the app before showing a modal", exc_info=True)


def run_modal(alert: Any) -> int:
    """Show a modal after raising the app and return its response code."""
    activate_app()
    return int(alert.runModal())

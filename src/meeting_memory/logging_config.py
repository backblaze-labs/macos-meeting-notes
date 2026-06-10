"""Logging setup for meeting-memory."""

from __future__ import annotations

import logging
from pathlib import Path

LOG_DIR = Path.home() / "Library" / "Logs" / "meeting-memory"
LOG_FILE = LOG_DIR / "app.log"


def configure_logging(level: int = logging.INFO) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=LOG_FILE,
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

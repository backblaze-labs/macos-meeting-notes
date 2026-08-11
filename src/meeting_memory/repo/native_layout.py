"""Resolve the native helper from one captured runtime layout."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from meeting_memory.config.runtime_layout import current_runtime_layout
from meeting_memory.types.runtime_layout import RuntimeLayout

HELPER_ENV_VAR = "MEETING_MEMORY_CAPTURE_HELPER"
HELPER_NAME = "MeetingMemoryCapture"
BUILD_DIR_NAME = ".build"


def resolve_native_capture_helper(
    runtime_layout: RuntimeLayout | None = None,
    *,
    environment: Mapping[str, str] | None = None,
) -> Path | None:
    """Return the exact executable helper; env overrides are development-only."""

    layout = runtime_layout or current_runtime_layout()
    process = os.environ if environment is None else environment
    configured = process.get(HELPER_ENV_VAR) if layout.project_root is not None else None
    candidates = (
        layout.resolve_checkout_path(configured) if configured else None,
        layout.native_helper_path,
    )
    return next(
        (
            candidate
            for candidate in candidates
            if candidate is not None and candidate.is_file() and os.access(candidate, os.X_OK)
        ),
        None,
    )

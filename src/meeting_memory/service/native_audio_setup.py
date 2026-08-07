"""Build orchestration for the native macOS audio helper."""

from __future__ import annotations

import sys
from pathlib import Path

from meeting_memory.repo.native_audio import (
    build_native_capture_helper,
    default_build_helper_path,
)


def build_native_audio(project_dir: Path) -> int:
    """Build the helper in the project's local build directory."""
    output = build_native_capture_helper(project_dir, default_build_helper_path(project_dir))
    sys.stderr.write(f"Native audio helper built: {output}\n")
    return 0

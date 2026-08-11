"""Build orchestration for the native macOS audio helper."""

from __future__ import annotations

import sys
from pathlib import Path

from meeting_memory.repo.native_audio import (
    build_native_capture_helper,
    default_build_helper_path,
)


def build_native_audio(project_dir: Path) -> int:
    """Build the capture helper and AAC encoder in the local build directory."""
    output = build_native_capture_helper(project_dir, default_build_helper_path(project_dir))
    sys.stderr.write(f"Native audio toolchain built: {output.parent}\n")
    return 0

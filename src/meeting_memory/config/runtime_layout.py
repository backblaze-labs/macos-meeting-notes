"""Capture the process-wide filesystem layout without consulting cwd."""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

from meeting_memory.types.runtime_layout import RuntimeLayout


@lru_cache(maxsize=1)
def current_runtime_layout() -> RuntimeLayout:
    """Return one trusted layout snapshot for the lifetime of this process."""

    home = Path.home()
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable)
        return RuntimeLayout.bundled(executable.parents[2], home=home)

    project_root = Path(__file__).parents[3]
    return RuntimeLayout.development(project_root, home=home)

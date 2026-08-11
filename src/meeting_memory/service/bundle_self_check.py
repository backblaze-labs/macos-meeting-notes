"""Secret-free frozen bundle validation for release smoke tests."""

from __future__ import annotations

import importlib
import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from meeting_memory.config.runtime_layout import current_runtime_layout
from meeting_memory.types.runtime_layout import RuntimeLayout, RuntimeMode
from meeting_memory.version import APP_VERSION

REQUIRED_IMPORTS = (
    "AppKit",
    "Foundation",
    "anthropic",
    "assemblyai",
    "boto3",
    "botocore",
    "certifi",
    "google_auth_oauthlib.flow",
    "googleapiclient.discovery",
    "keyring.backends.macOS",
    "rumps",
)
RESOURCE_PATHS = (
    Path("MeetingMemory.icns"),
    Path("LICENSE"),
    Path("THIRD_PARTY_NOTICES.md"),
    Path("meeting_memory/ui/assets/robot-template.png"),
    Path("meeting_memory/ui/assets/robot-template.svg"),
)


@dataclass(frozen=True, slots=True)
class BundleSelfCheckReport:
    """Value-free smoke result safe for CI logs."""

    ready: bool
    version: str
    imports_checked: int
    resources_checked: int

    def render(self) -> str:
        return json.dumps(
            {
                "event": "bundle-self-check",
                "ready": self.ready,
                "version": self.version,
                "imports_checked": self.imports_checked,
                "resources_checked": self.resources_checked,
            },
            sort_keys=True,
            separators=(",", ":"),
        )


def inspect_bundle(
    runtime_layout: RuntimeLayout | None = None,
    *,
    importer: Callable[[str], object] = importlib.import_module,
) -> BundleSelfCheckReport:
    """Import packaged boundaries and validate immutable bundle resources."""

    layout = runtime_layout or current_runtime_layout()
    if layout.mode is not RuntimeMode.BUNDLED:
        raise RuntimeError("bundle self-check requires bundled execution")
    if not getattr(sys, "frozen", False) and runtime_layout is None:
        raise RuntimeError("bundle self-check requires a frozen executable")

    helper = layout.native_helper_path
    if not helper.is_file() or not os.access(helper, os.X_OK):
        raise RuntimeError("bundled native helper is missing or not executable")
    for relative in RESOURCE_PATHS:
        resource = layout.resources_path / relative
        if not resource.is_file():
            raise RuntimeError("a required bundled resource is missing")
    for module_name in REQUIRED_IMPORTS:
        importer(module_name)
    return BundleSelfCheckReport(True, APP_VERSION, len(REQUIRED_IMPORTS), len(RESOURCE_PATHS))


def run_bundle_self_check() -> int:
    """Render one sanitized terminal result without external I/O."""

    try:
        report = inspect_bundle()
    except Exception:
        sys.stderr.write("Bundle self-check failed safely. Reinstall the application.\n")
        return 2
    sys.stdout.write(report.render() + "\n")
    return 0

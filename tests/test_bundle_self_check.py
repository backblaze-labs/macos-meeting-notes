"""Frozen self-check remains value-free and read-only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from meeting_memory.service.bundle_self_check import (
    REQUIRED_IMPORTS,
    RESOURCE_PATHS,
    inspect_bundle,
)
from meeting_memory.types.runtime_layout import RuntimeLayout
from meeting_memory.version import APP_VERSION


def _bundle(tmp_path: Path) -> tuple[RuntimeLayout, Path]:
    bundle = tmp_path / "Meeting Memory.app"
    layout = RuntimeLayout.bundled(bundle, home=tmp_path / "home")
    helper = layout.native_helper_path
    helper.parent.mkdir(parents=True)
    helper.write_bytes(b"helper")
    helper.chmod(0o755)
    for relative in RESOURCE_PATHS:
        resource = layout.resources_path / relative
        resource.parent.mkdir(parents=True, exist_ok=True)
        resource.write_bytes(b"resource")
    return layout, bundle


def test_bundle_self_check_imports_allowlist_and_reports_no_paths(tmp_path: Path) -> None:
    layout, bundle = _bundle(tmp_path)
    imported: list[str] = []

    report = inspect_bundle(layout, importer=lambda name: imported.append(name))
    rendered = report.render()
    payload = json.loads(rendered)

    assert imported == list(REQUIRED_IMPORTS)
    assert payload == {
        "event": "bundle-self-check",
        "imports_checked": len(REQUIRED_IMPORTS),
        "ready": True,
        "resources_checked": len(RESOURCE_PATHS),
        "version": APP_VERSION,
    }
    assert str(bundle) not in rendered
    assert str(layout.home) not in rendered


def test_bundle_self_check_rejects_missing_resource_before_imports(tmp_path: Path) -> None:
    layout, _bundle_path = _bundle(tmp_path)
    (layout.resources_path / RESOURCE_PATHS[0]).unlink()
    imported: list[str] = []

    with pytest.raises(RuntimeError, match="required bundled resource"):
        inspect_bundle(layout, importer=lambda name: imported.append(name))

    assert imported == []

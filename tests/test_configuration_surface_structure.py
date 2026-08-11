"""Reachability and parity guards for the native configuration surface."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "src" / "meeting_memory" / "ui"


def test_active_trays_cannot_reach_legacy_environment_writers() -> None:
    paths = tuple(
        UI / name
        for name in (
            "tray.py",
            "setup_tray.py",
            "runtime_app.py",
            "configuration_surface.py",
            "configuration_forms.py",
            "migration_form.py",
            "prompt_form.py",
            "submenus.py",
        )
    )
    forbidden = {
        "meeting_memory.ui.preferences",
        "meeting_memory.ui.notes_prompt",
    }
    for path in paths:
        source = path.read_text(encoding="utf-8")
        imports = {
            node.module for node in ast.walk(ast.parse(source)) if isinstance(node, ast.ImportFrom)
        }
        assert imports.isdisjoint(forbidden)
        assert "update_env_file" not in source
        assert "open_preferences_window" not in source


def test_setup_uses_no_ambient_runtime_settings_for_prompt_path() -> None:
    source = (UI / "setup_tray.py").read_text(encoding="utf-8")

    assert "RuntimeSettings" not in source
    assert "Settings(" not in source
    assert "notes_prompt_available=False" in source

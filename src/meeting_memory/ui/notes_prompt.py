"""Compatibility editor for Notes instructions and local Markdown layout."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from meeting_memory.config.notes_template import (
    compose_notes_prompt_document,
    parse_notes_prompt_document,
)
from meeting_memory.config.settings import Settings
from meeting_memory.service.summary_prompt import (
    read_summary_prompt,
    summary_prompt_path,
    write_summary_prompt,
)
from meeting_memory.types.configuration_surface import PromptDraft
from meeting_memory.ui import load_rumps
from meeting_memory.ui.prompt_form import edit_prompt

PromptEditor = Callable[[str, Path], str | None]


def open_notes_prompt_window(
    settings: Settings,
    *,
    rumps_module: Any | None = None,
    prompt_editor: PromptEditor | None = None,
) -> bool:
    rumps = rumps_module or load_rumps()
    path = summary_prompt_path(settings)
    try:
        current_prompt = read_summary_prompt(settings)
    except Exception:
        _alert(
            rumps,
            "Notes Customization",
            "The Notes configuration could not be loaded safely.",
        )
        return False

    try:
        edited_prompt = (
            prompt_editor(current_prompt, path)
            if prompt_editor is not None
            else _prompt_notes_text(current_prompt, path, rumps)
        )
    except Exception:
        edited_prompt = _prompt_notes_fallback(current_prompt, path, rumps)
    if edited_prompt is None:
        return False
    if not edited_prompt.strip():
        _alert(
            rumps,
            "Notes Customization",
            "The Notes instructions and layout cannot be empty.",
        )
        return False

    try:
        saved_path = write_summary_prompt(settings, edited_prompt)
    except Exception:
        _alert(
            rumps,
            "Notes Customization",
            "Keep {summary}, {decisions}, and {action_items}, then try again.",
        )
        return False

    _alert(
        rumps,
        "Notes Customization Saved",
        f"The next notes generation will use {saved_path}.",
    )
    return True


def _prompt_notes_text(prompt: str, path: Path, rumps: Any) -> str | None:
    del path, rumps
    updated = edit_prompt(PromptDraft(prompt))
    return None if updated is None else updated.text


def _prompt_notes_fallback(prompt: str, path: Path, rumps: Any) -> str | None:
    document = parse_notes_prompt_document(prompt)
    instructions_window = rumps.Window(
        message=(
            "These instructions and a speaker-confirmed transcript excerpt are sent to "
            "Anthropic only when Notes runs. Report structure is configured separately."
        ),
        title="AI Instructions",
        default_text=document.instructions,
        ok="Continue",
        cancel=True,
        dimensions=(720, 420),
    )
    instructions = instructions_window.run()
    if not getattr(instructions, "clicked", False):
        return None
    layout_window = rumps.Window(
        message=(
            "This Markdown stays on your Mac and controls notes.md. Keep {summary}, "
            "{decisions}, and {action_items}. "
            f"Saving updates {path}."
        ),
        title="Report Layout",
        default_text=document.report_template,
        ok="Save Changes",
        cancel=True,
        dimensions=(720, 420),
    )
    layout = layout_window.run()
    if not getattr(layout, "clicked", False):
        return None
    return compose_notes_prompt_document(str(instructions.text), str(layout.text))


def _alert(rumps: Any, title: str, message: str) -> None:
    rumps.alert(title=title, message=message)

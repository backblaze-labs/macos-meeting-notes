"""Native editor for the notes-generation prompt."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from meeting_memory.config.defaults import DEFAULT_SUMMARY_PROMPT_TEMPLATE
from meeting_memory.config.settings import Settings
from meeting_memory.service.summary_prompt import (
    read_summary_prompt,
    summary_prompt_path,
    write_summary_prompt,
)
from meeting_memory.ui import load_rumps

RESTORE_DEFAULT_RESPONSE = 1002
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
    except Exception as exc:
        _alert(rumps, "Notes Prompt", _format_exception(exc))
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

    try:
        saved_path = write_summary_prompt(settings, edited_prompt)
    except Exception as exc:
        _alert(rumps, "Notes Prompt", _format_exception(exc))
        return False

    _alert(
        rumps,
        "Notes Prompt Saved",
        f"The next notes generation will use {saved_path}.",
    )
    return True


def _prompt_notes_text(prompt: str, path: Path, rumps: Any) -> str | None:
    from AppKit import NSAlert, NSFont, NSMakeRect, NSScrollView, NSTextView

    while True:
        text_view = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, 720, 420))
        text_view.setString_(prompt)
        text_view.setEditable_(True)
        text_view.setSelectable_(True)
        text_view.setRichText_(False)
        text_view.setFont_(NSFont.userFixedPitchFontOfSize_(12))
        text_view.setHorizontallyResizable_(False)
        text_view.setVerticallyResizable_(True)
        _disable_smart_replacements(text_view)

        scroll_view = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, 720, 420))
        scroll_view.setDocumentView_(text_view)
        scroll_view.setHasVerticalScroller_(True)
        scroll_view.setHasHorizontalScroller_(False)

        alert = NSAlert.alloc().init()
        alert.setMessageText_("Notes Prompt")
        alert.setInformativeText_(
            "Adds instructions for Summary, Decisions, and Action Items; "
            "the JSON output contract is always enforced. "
            "Use {transcript} where the transcript should appear; otherwise it is appended. "
            f"Changes apply to the next notes generation.\n{path}"
        )
        alert.addButtonWithTitle_("Save")
        alert.addButtonWithTitle_("Cancel")
        alert.addButtonWithTitle_("Restore Default")
        alert.setAccessoryView_(scroll_view)
        response = int(alert.runModal())
        if response in {1, 1000}:
            value = str(text_view.string())
            if value.strip():
                return value
            _alert(rumps, "Notes Prompt", "The notes prompt cannot be empty.")
            prompt = value
            continue
        if response == RESTORE_DEFAULT_RESPONSE:
            prompt = DEFAULT_SUMMARY_PROMPT_TEMPLATE
            continue
        return None


def _prompt_notes_fallback(prompt: str, path: Path, rumps: Any) -> str | None:
    window = rumps.Window(
        message=(
            "The JSON output contract is fixed. Use {transcript} where the transcript "
            "should appear; otherwise it is appended. "
            f"Saving updates {path}."
        ),
        title="Notes Prompt",
        default_text=prompt,
        ok="Save",
        cancel=True,
        dimensions=(720, 420),
    )
    response = window.run()
    if not getattr(response, "clicked", False):
        return None
    return str(response.text)


def _disable_smart_replacements(text_view: Any) -> None:
    for selector in (
        "setAutomaticQuoteSubstitutionEnabled_",
        "setAutomaticDashSubstitutionEnabled_",
        "setAutomaticTextReplacementEnabled_",
    ):
        setter = getattr(text_view, selector, None)
        if callable(setter):
            setter(False)


def _alert(rumps: Any, title: str, message: str) -> None:
    rumps.alert(title=title, message=message)


def _format_exception(exc: Exception) -> str:
    return str(exc).strip() or exc.__class__.__name__

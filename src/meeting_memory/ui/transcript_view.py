"""Transcript review helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Protocol


class Runner(Protocol):
    def __call__(self, args: list[str], **kwargs: Any) -> Any:
        """Run a subprocess-style command."""


def open_markdown_in_vscode(
    path: Path,
    *,
    runner: Runner = subprocess.run,
) -> None:
    result = runner(["open", "-a", "Visual Studio Code", str(path)], check=False)
    if getattr(result, "returncode", 0):
        runner(["open", str(path)], check=False)


def show_transcript_window(path: Path) -> None:
    from AppKit import NSAlert, NSMakeRect, NSScrollView, NSTextView

    text_view = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, 720, 420))
    text_view.setString_(_read_markdown(path))
    text_view.setEditable_(False)
    text_view.setSelectable_(True)
    text_view.setHorizontallyResizable_(False)
    text_view.setVerticallyResizable_(True)

    scroll_view = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, 720, 420))
    scroll_view.setDocumentView_(text_view)
    scroll_view.setHasVerticalScroller_(True)
    scroll_view.setHasHorizontalScroller_(False)

    alert = NSAlert.alloc().init()
    alert.setMessageText_("Full Transcript")
    alert.setInformativeText_(path.name)
    alert.addButtonWithTitle_("Done")
    alert.setAccessoryView_(scroll_view)
    alert.runModal()


def _read_markdown(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception as exc:
        return str(exc).strip() or exc.__class__.__name__

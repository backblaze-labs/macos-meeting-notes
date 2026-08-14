"""Rendered native preview for the visual Notes report layout editor."""

from __future__ import annotations

from typing import Any

from meeting_memory.config.notes_template import NotesVisualLayout

_SAMPLE_CONTENT = {
    "summary": "Project context, risks, and progress at a glance.",
    "decisions": "• Keep local Markdown as the source of truth.",
    "action_items": "• Maya — verify upload behavior before Friday.",
}


def update_notes_preview(text_view: Any, layout: NotesVisualLayout) -> None:
    from AppKit import (
        NSColor,
        NSFont,
        NSFontAttributeName,
        NSForegroundColorAttributeName,
        NSMutableAttributedString,
        NSMutableParagraphStyle,
        NSParagraphStyleAttributeName,
    )

    output = NSMutableAttributedString.alloc().init()
    title_style = NSMutableParagraphStyle.alloc().init()
    title_style.setParagraphSpacing_(8)
    section_style = NSMutableParagraphStyle.alloc().init()
    section_style.setParagraphSpacingBefore_(14)
    section_style.setParagraphSpacing_(5)
    body_style = NSMutableParagraphStyle.alloc().init()
    body_style.setParagraphSpacing_(2)

    _append(
        output,
        f"{layout.title}\n",
        {
            NSFontAttributeName: NSFont.boldSystemFontOfSize_(20),
            NSForegroundColorAttributeName: NSColor.labelColor(),
            NSParagraphStyleAttributeName: title_style,
        },
    )
    metadata: list[str] = []
    if layout.include_date:
        metadata.append("August 14, 2026")
    if layout.include_source:
        metadata.append("Source: transcript.md")
    if metadata:
        _append(
            output,
            f"{'  ·  '.join(metadata)}\n",
            {
                NSFontAttributeName: NSFont.systemFontOfSize_(10),
                NSForegroundColorAttributeName: NSColor.secondaryLabelColor(),
                NSParagraphStyleAttributeName: body_style,
            },
        )
    for section in layout.sections:
        _append(
            output,
            f"{section.heading}\n",
            {
                NSFontAttributeName: NSFont.boldSystemFontOfSize_(13),
                NSForegroundColorAttributeName: NSColor.labelColor(),
                NSParagraphStyleAttributeName: section_style,
            },
        )
        _append(
            output,
            f"{_SAMPLE_CONTENT[section.key]}\n",
            {
                NSFontAttributeName: NSFont.systemFontOfSize_(12),
                NSForegroundColorAttributeName: NSColor.labelColor(),
                NSParagraphStyleAttributeName: body_style,
            },
        )
    text_view.textStorage().setAttributedString_(output)


def _append(output: Any, text: str, attributes: dict[Any, Any]) -> None:
    from AppKit import NSAttributedString

    fragment = NSAttributedString.alloc().initWithString_attributes_(text, attributes)
    output.appendAttributedString_(fragment)

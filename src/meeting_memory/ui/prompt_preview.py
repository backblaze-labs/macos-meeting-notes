"""Rendered native preview for configurable Notes profiles."""

from __future__ import annotations

from typing import Any

from meeting_memory.types.notes_profile import (
    NotesProfile,
    NotesSectionAudience,
    NotesSectionFormat,
)

_KNOWN_SAMPLES = {
    "summary": "The team aligned on launch scope and identified one delivery risk.",
    "decisions": "• Keep local Markdown as the source of truth.",
    "action_items": "☐ Maya — verify upload behavior before Friday.",
    "participant_updates": (
        "• Maya — upload validation is ready; monitoring remains.\n"
        "• Alex — documentation is in review; no blocker reported."
    ),
    "my_tasks": "☐ Review the launch checklist.",
}


def update_notes_profile_preview(text_view: Any, profile: NotesProfile) -> None:
    from AppKit import NSColor, NSFont, NSMutableAttributedString

    output = NSMutableAttributedString.alloc().init()
    title_style = _style(8)
    section_style = _style(5, before=14)
    body_style = _style(2)
    _append(
        output,
        f"{profile.report_title}\n",
        NSFont.boldSystemFontOfSize_(20),
        NSColor.labelColor(),
        title_style,
    )
    metadata: list[str] = []
    if profile.include_date:
        metadata.append("August 17, 2026")
    if profile.include_source:
        metadata.append("Source: transcript.md")
    if metadata:
        _append(
            output,
            f"{'  ·  '.join(metadata)}\n",
            NSFont.systemFontOfSize_(10),
            NSColor.secondaryLabelColor(),
            body_style,
        )
    for section in profile.sections:
        _append(
            output,
            f"{section.title}\n",
            NSFont.boldSystemFontOfSize_(13),
            NSColor.labelColor(),
            section_style,
        )
        _append(
            output,
            f"{_sample_content(section.key, section.output_format, section.audience)}\n",
            NSFont.systemFontOfSize_(12),
            NSColor.labelColor(),
            body_style,
        )
    text_view.textStorage().setAttributedString_(output)


def _sample_content(
    key: str, output_format: NotesSectionFormat, audience: NotesSectionAudience
) -> str:
    if key in _KNOWN_SAMPLES:
        return _KNOWN_SAMPLES[key]
    subject = {
        NotesSectionAudience.MEETING: "The meeting's most relevant point.",
        NotesSectionAudience.EACH_PARTICIPANT: "Maya — a concise participant update.",
        NotesSectionAudience.ME: "Your relevant outcome from the meeting.",
    }[audience]
    return {
        NotesSectionFormat.PARAGRAPH: subject,
        NotesSectionFormat.BULLETS: f"• {subject}",
        NotesSectionFormat.CHECKLIST: f"☐ {subject}",
    }[output_format]


def _style(spacing: float, *, before: float = 0) -> Any:
    from AppKit import NSMutableParagraphStyle

    style = NSMutableParagraphStyle.alloc().init()
    style.setParagraphSpacing_(spacing)
    if before:
        style.setParagraphSpacingBefore_(before)
    return style


def _append(output: Any, text: str, font: Any, color: Any, style: Any) -> None:
    from AppKit import (
        NSAttributedString,
        NSFontAttributeName,
        NSForegroundColorAttributeName,
        NSParagraphStyleAttributeName,
    )

    fragment = NSAttributedString.alloc().initWithString_attributes_(
        text,
        {
            NSFontAttributeName: font,
            NSForegroundColorAttributeName: color,
            NSParagraphStyleAttributeName: style,
        },
    )
    output.appendAttributedString_(fragment)

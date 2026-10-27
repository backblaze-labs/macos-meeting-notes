"""Native speaker-review controls and draft rendering helpers."""

import re
from typing import Any

from meeting_memory.types.transcript import SpeakerReviewState

MANUAL_OPTION = "Manual..."


def _options_for(state: SpeakerReviewState, label: str) -> list[str]:
    options = list(state.speaker_candidates)
    alias = state.speaker_aliases.get(label, "")
    if alias and alias not in options:
        options.append(alias)
    options.append(MANUAL_OPTION)
    return options


def _selected_option(state: SpeakerReviewState, label: str, options: list[str]) -> str:
    alias = state.speaker_aliases.get(label, state.speaker_suggestions.get(label, ""))
    return alias if alias in options else MANUAL_OPTION


def _label_field(text: str, x: int, y: int, width: int, height: int) -> Any:
    from AppKit import NSMakeRect, NSTextField

    field = NSTextField.alloc().initWithFrame_(NSMakeRect(x, y, width, height))
    field.setStringValue_(text)
    field.setBezeled_(False)
    field.setDrawsBackground_(False)
    field.setEditable_(False)
    field.setSelectable_(False)
    return field


def _hint_field(text: str, x: int, y: int, width: int, height: int) -> Any:
    from AppKit import NSFont

    field = _label_field(text, x, y, width, height)
    field.setFont_(NSFont.systemFontOfSize_(12))
    return field


def _aliases_from_rows(rows: list[tuple[str, Any, Any]]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for label, popup, manual_field in rows:
        selected = str(popup.titleOfSelectedItem())
        manual = str(manual_field.stringValue()).strip()
        aliases[label] = manual if selected == MANUAL_OPTION else selected.strip()
    return aliases


def _speaker_hint(state: SpeakerReviewState, label: str) -> str:
    text = state.speaker_longest_lines.get(label, "")
    hint = f"Longest line: {_truncate(text, 170)}" if text else "Longest line unavailable"
    evidence = state.speaker_evidence.get(label)
    if evidence and not state.speaker_aliases.get(label):
        hint += f"\nSuggested name evidence: {_truncate(evidence, 155)}"
    return hint


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3].rstrip()}..."


def _alias_text(state: SpeakerReviewState) -> str:
    return "\n".join(
        f"{label}={state.speaker_aliases.get(label) or state.speaker_suggestions.get(label, '')}"
        for label in state.speaker_labels
    )


def _display_label(label: str) -> str:
    return f"Speaker {label}" if re.fullmatch(r"[A-Z]+", label) else label


def _parse_alias_text(text: str) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        label, alias = line.split("=", 1)
        aliases[label.strip()] = alias.strip()
    return aliases

"""Speaker review windows for diarized transcripts."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from meeting_memory.types.transcript import SpeakerReviewState
from meeting_memory.ui.transcript_view import (
    open_markdown_in_vscode,
    show_transcript_window,
)

MANUAL_OPTION = "Manual..."
OK_RESPONSES = {1, 1000}
OPEN_MARKDOWN_RESPONSE = 1002
FULL_TRANSCRIPT_RESPONSE = 1003
SPEAKER_REVIEW_MAX_HEIGHT = 430

PromptAliases = Callable[[SpeakerReviewState], dict[str, str] | None]
OpenConversation = Callable[[Path], None]
ShowTranscript = Callable[[Path], None]


@dataclass(frozen=True)
class SpeakerReviewActions:
    load_review: Callable[[Path], SpeakerReviewState]
    confirm_aliases: Callable[[Path, dict[str, str]], Path]
    generate_notes: Callable[[Path], None]


def open_speaker_review_window(
    meeting_path: Path,
    actions: SpeakerReviewActions,
    *,
    rumps_module: Any | None = None,
    prompt_aliases: PromptAliases | None = None,
    open_conversation: OpenConversation = open_markdown_in_vscode,
    show_transcript: ShowTranscript = show_transcript_window,
) -> bool:
    rumps = rumps_module or _load_rumps()
    try:
        state = actions.load_review(meeting_path)
    except Exception as exc:
        _alert(rumps, "Review Speakers", _format_exception(exc))
        return False

    if not state.speaker_labels:
        _alert(rumps, "Review Speakers", "No speaker labels found in transcript.md.")
        return False

    aliases = (
        prompt_aliases(state)
        if prompt_aliases is not None
        else _prompt_aliases(state, open_conversation, show_transcript)
    )
    if aliases is None:
        return False

    try:
        actions.confirm_aliases(meeting_path, aliases)
    except Exception as exc:
        _alert(rumps, "Review Speakers", _format_exception(exc))
        return False

    try:
        actions.generate_notes(meeting_path)
    except Exception as exc:
        _alert(rumps, "Generate Notes", _format_exception(exc))
        return False
    return True


def _prompt_aliases(
    state: SpeakerReviewState,
    open_conversation: OpenConversation,
    show_transcript: ShowTranscript,
):
    try:
        return _prompt_aliases_appkit(state, open_conversation, show_transcript)
    except Exception:
        return _prompt_aliases_text(state, _load_rumps())


def _prompt_aliases_appkit(
    state: SpeakerReviewState,
    open_conversation: OpenConversation,
    show_transcript: ShowTranscript,
) -> dict[str, str] | None:
    from AppKit import (
        NSAlert,
        NSMakePoint,
        NSMakeRect,
        NSPopUpButton,
        NSScrollView,
        NSTextField,
        NSView,
    )

    while True:
        width = 640
        row_height = 82
        content_height = max(140, 62 + len(state.speaker_labels) * row_height)
        height = min(content_height, SPEAKER_REVIEW_MAX_HEIGHT)
        view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, width, content_height))
        rows: list[tuple[str, Any, Any]] = []

        for index, label in enumerate(state.speaker_labels):
            y = content_height - 38 - index * row_height
            label_field = _label_field(_display_label(label), 0, y, 120, 22)
            popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
                NSMakeRect(132, y - 3, 190, 26),
                False,
            )
            options = _options_for(state, label)
            popup.addItemsWithTitles_(options)
            popup.selectItemWithTitle_(_selected_option(state, label, options))

            manual_field = NSTextField.alloc().initWithFrame_(NSMakeRect(334, y - 3, 286, 24))
            manual_field.setPlaceholderString_("Manual name")
            alias = state.speaker_aliases.get(label, "")
            if alias and alias not in state.speaker_candidates:
                manual_field.setStringValue_(alias)

            view.addSubview_(label_field)
            view.addSubview_(popup)
            view.addSubview_(manual_field)
            view.addSubview_(_hint_field(_speaker_hint(state, label), 132, y - 52, 488, 46))
            rows.append((label, popup, manual_field))

        scroll_view = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))
        scroll_view.setDocumentView_(view)
        scroll_view.setHasVerticalScroller_(content_height > height)
        scroll_view.setHasHorizontalScroller_(False)
        scroll_view.setAutohidesScrollers_(False)
        clip_view = scroll_view.contentView()
        clip_view.scrollToPoint_(NSMakePoint(0, max(0, content_height - height)))
        scroll_view.reflectScrolledClipView_(clip_view)

        alert = NSAlert.alloc().init()
        alert.setMessageText_("Review Speakers")
        alert.setInformativeText_(_review_message(state))
        alert.addButtonWithTitle_("Confirm")
        alert.addButtonWithTitle_("Cancel")
        alert.addButtonWithTitle_("Open in VS Code")
        alert.addButtonWithTitle_("Full Transcript")
        alert.setAccessoryView_(scroll_view)
        response = alert.runModal()
        if _is_ok_response(response):
            return _aliases_from_rows(rows)
        if int(response) == OPEN_MARKDOWN_RESPONSE:
            state = replace(state, speaker_aliases=_aliases_from_rows(rows))
            open_conversation(state.transcript_path)
            continue
        if int(response) == FULL_TRANSCRIPT_RESPONSE:
            state = replace(state, speaker_aliases=_aliases_from_rows(rows))
            show_transcript(state.transcript_path)
            continue
        return None


def _prompt_aliases_text(state: SpeakerReviewState, rumps: Any) -> dict[str, str] | None:
    window = rumps.Window(
        message=_review_message(state) + "\nUse one label=name mapping per line.",
        title="Review Speakers",
        default_text=_alias_text(state),
        ok="Confirm",
        cancel=True,
        dimensions=(520, 160),
    )
    response = window.run()
    if not getattr(response, "clicked", False):
        return None
    return _parse_alias_text(str(response.text))


def _alert(
    rumps: Any,
    title: str,
    message: str,
    *,
    ok: str | None = None,
    cancel: str | bool | None = None,
) -> int:
    alert = getattr(rumps, "alert", None)
    if callable(alert):
        return int(alert(title=title, message=message, ok=ok, cancel=cancel))
    notify = getattr(rumps, "notification", None)
    if callable(notify):
        notify(title, "", message)
    return 0


def _review_message(state: SpeakerReviewState) -> str:
    candidates = ", ".join(state.speaker_candidates) or "No candidates found"
    speakers = ", ".join(_display_label(label) for label in state.speaker_labels)
    return f"Detected speakers: {speakers}\nCandidates: {candidates}"


def _options_for(state: SpeakerReviewState, label: str) -> list[str]:
    options = list(state.speaker_candidates)
    alias = state.speaker_aliases.get(label, "")
    if alias and alias not in options:
        options.append(alias)
    options.append(MANUAL_OPTION)
    return options


def _selected_option(state: SpeakerReviewState, label: str, options: list[str]) -> str:
    alias = state.speaker_aliases.get(label, "")
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
    if not text:
        return "Longest line unavailable"
    return f"Longest line: {_truncate(text, 170)}"


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3].rstrip()}..."


def _alias_text(state: SpeakerReviewState) -> str:
    lines = []
    for label in state.speaker_labels:
        lines.append(f"{label}={state.speaker_aliases.get(label, '')}")
    return "\n".join(lines)


def _display_label(label: str) -> str:
    if re.fullmatch(r"[A-Z]+", label):
        return f"Speaker {label}"
    return label


def _parse_alias_text(text: str) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        label, alias = line.split("=", 1)
        aliases[label.strip()] = alias.strip()
    return aliases


def _is_ok_response(response: object) -> bool:
    try:
        return int(response) in OK_RESPONSES
    except (TypeError, ValueError):
        return bool(response)


def _format_exception(exc: Exception) -> str:
    return str(exc).strip() or exc.__class__.__name__


def _load_rumps():
    import rumps

    return rumps

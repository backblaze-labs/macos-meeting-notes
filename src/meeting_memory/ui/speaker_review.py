"""Speaker review windows for diarized transcripts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from meeting_memory.types.transcript import SpeakerReviewState
from meeting_memory.ui.modal_focus import run_modal
from meeting_memory.ui.speaker_review_fields import (
    _alias_text,
    _aliases_from_rows,
    _display_label,
    _hint_field,
    _label_field,
    _options_for,
    _parse_alias_text,
    _selected_option,
    _speaker_hint,
)
from meeting_memory.ui.transcript_view import open_markdown_in_vscode, show_transcript_window

KEEP_LABELS_RESPONSE = 1001
OPEN_MARKDOWN_RESPONSE = 1003
FULL_TRANSCRIPT_RESPONSE = 1004
SPEAKER_REVIEW_MAX_HEIGHT = 430
KEEP_SPEAKER_LABELS = object()

PromptResult = dict[str, str] | object | None
PromptAliases = Callable[[SpeakerReviewState], PromptResult]
OpenConversation = ShowTranscript = Callable[[Path], None]


@dataclass(frozen=True)
class SpeakerReviewActions:
    load_review: Callable[[Path], SpeakerReviewState]
    confirm_aliases: Callable[[Path, dict[str, str]], Path]
    keep_labels: Callable[[Path], Path]
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

    def remember_draft(aliases: dict[str, str]) -> None:
        nonlocal state
        state = replace(state, speaker_aliases=dict(aliases), speaker_suggestions={})

    while True:
        aliases = (
            prompt_aliases(state)
            if prompt_aliases is not None
            else _prompt_aliases(state, open_conversation, show_transcript, remember_draft)
        )
        if aliases is None:
            return False
        if aliases is not KEEP_SPEAKER_LABELS:
            remember_draft(aliases)
            missing = [
                label for label in state.speaker_labels if not aliases.get(label, "").strip()
            ]
            if missing:
                _alert(rumps, "Review Speakers", "Assign a name to: " + ", ".join(missing))
                continue
        try:
            if aliases is KEEP_SPEAKER_LABELS:
                actions.keep_labels(meeting_path)
            else:
                actions.confirm_aliases(meeting_path, aliases)
        except Exception as exc:
            _alert(rumps, "Review Speakers", _format_exception(exc))
            continue
        break

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
    remember_draft: Callable[[dict[str, str]], None],
):
    try:
        return _prompt_aliases_appkit(state, open_conversation, show_transcript, remember_draft)
    except Exception:
        return _prompt_aliases_text(state, _load_rumps(), remember_draft)


def _prompt_aliases_appkit(
    state: SpeakerReviewState,
    open_conversation: OpenConversation,
    show_transcript: ShowTranscript,
    remember_draft: Callable[[dict[str, str]], None] = lambda _aliases: None,
) -> PromptResult:
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
        row_height = 126
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
            view.addSubview_(_hint_field(_speaker_hint(state, label), 132, y - 96, 488, 90))
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
        alert.addButtonWithTitle_("Confirm Names")
        alert.addButtonWithTitle_("Keep Speaker Labels")
        alert.addButtonWithTitle_("Cancel")
        alert.addButtonWithTitle_("Open in VS Code")
        alert.addButtonWithTitle_("Full Transcript")
        alert.setAccessoryView_(scroll_view)
        response = run_modal(alert)
        aliases = _aliases_from_rows(rows)
        remember_draft(aliases)
        if int(response) in {1, 1000}:
            return aliases
        if int(response) == OPEN_MARKDOWN_RESPONSE:
            state = replace(state, speaker_aliases=aliases, speaker_suggestions={})
            open_conversation(state.transcript_path)
            continue
        if int(response) == FULL_TRANSCRIPT_RESPONSE:
            state = replace(state, speaker_aliases=aliases, speaker_suggestions={})
            show_transcript(state.transcript_path)
            continue
        if int(response) == KEEP_LABELS_RESPONSE:
            return KEEP_SPEAKER_LABELS
        return None


def _prompt_aliases_text(
    state: SpeakerReviewState,
    rumps: Any,
    remember_draft: Callable[[dict[str, str]], None] = lambda _aliases: None,
) -> PromptResult:
    window = rumps.Window(
        message=_review_message(state)
        + "\nUse label=name mappings, or leave every name blank to keep the labels.",
        title="Review Speakers",
        default_text=_alias_text(state),
        ok="Confirm",
        cancel=True,
        dimensions=(520, 160),
    )
    response = window.run()
    if not getattr(response, "clicked", False):
        return None
    aliases = _parse_alias_text(str(response.text))
    remember_draft(aliases)
    return aliases if any(aliases.values()) else KEEP_SPEAKER_LABELS


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
    message = (
        f"Detected speakers: {speakers}\nCandidates: {candidates}\n"
        "Assign every speaker a name. To keep one label, enter its text as the manual name "
        "(for example, Unknown). Keep Speaker Labels keeps all labels."
    )
    return f"{message}\n{state.suggestion_message}" if state.suggestion_message else message


def _format_exception(exc: Exception) -> str:
    return str(exc).strip() or exc.__class__.__name__


def _load_rumps():
    import rumps

    return rumps

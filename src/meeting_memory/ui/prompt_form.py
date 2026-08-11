"""Main-thread-only native editor for a privately loaded Notes prompt."""

from meeting_memory.config.defaults import DEFAULT_SUMMARY_PROMPT_TEMPLATE
from meeting_memory.types.configuration_surface import PromptDraft
from meeting_memory.ui.configuration_forms import OK_RESPONSES

RESTORE_DEFAULT_RESPONSE = 1002


def edit_prompt(draft: PromptDraft) -> PromptDraft | None:
    from AppKit import NSAlert, NSFont, NSMakeRect, NSScrollView, NSTextView

    prompt = draft.text
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
        scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, 720, 420))
        scroll.setDocumentView_(text_view)
        scroll.setHasVerticalScroller_(True)
        scroll.setHasHorizontalScroller_(False)
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Notes Prompt")
        alert.setInformativeText_(
            "This prompt is sent to Anthropic with a speaker-confirmed transcript excerpt. "
            "The fixed JSON output contract is always enforced and the excerpt is capped at "
            "60,000 characters. Changes apply to the next Notes generation without restarting."
        )
        alert.addButtonWithTitle_("Save")
        alert.addButtonWithTitle_("Cancel")
        alert.addButtonWithTitle_("Restore Default")
        alert.setAccessoryView_(scroll)
        response = int(alert.runModal())
        if response in OK_RESPONSES:
            value = str(text_view.string())
            if value.strip():
                return PromptDraft(value)
            _show_empty_prompt()
            prompt = value
            continue
        if response == RESTORE_DEFAULT_RESPONSE:
            prompt = DEFAULT_SUMMARY_PROMPT_TEMPLATE
            continue
        return None


def _disable_smart_replacements(text_view) -> None:
    for selector in (
        "setAutomaticQuoteSubstitutionEnabled_",
        "setAutomaticDashSubstitutionEnabled_",
        "setAutomaticTextReplacementEnabled_",
    ):
        setter = getattr(text_view, selector, None)
        if callable(setter):
            setter(False)


def _show_empty_prompt() -> None:
    from AppKit import NSAlert

    alert = NSAlert.alloc().init()
    alert.setMessageText_("Notes Prompt")
    alert.setInformativeText_("The notes prompt cannot be empty.")
    alert.addButtonWithTitle_("OK")
    alert.runModal()

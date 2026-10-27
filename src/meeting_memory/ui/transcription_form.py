"""Native provider selection with explicit external-audio acceptance."""

from __future__ import annotations

from meeting_memory.types.configuration import SettingKey
from meeting_memory.types.transcription import ASSEMBLYAI_CONSENT_VERSION, TranscriptionProvider
from meeting_memory.ui.modal_focus import run_modal

OFFICIAL_SOURCES = (
    (
        "Model improvement opt-out",
        "https://www.assemblyai.com/docs/faq/how-to-opt-out-of-data-sharing-for-our-model-improvement-program",
    ),
    ("Data controls", "https://www.assemblyai.com/docs/data-controls"),
)
ASSEMBLYAI_NOTICE = (
    "Your meeting audio leaves your Mac and is sent to AssemblyAI automatically "
    "for new recordings after recording stops. Handling depends on your plan, "
    "contract, and account controls. The free plan participates in model improvement "
    "and you cannot opt out. A paid account can explicitly opt out in its account "
    "controls; exclusion is not automatic when you pay. Opt-out applies only to "
    "future requests. Meeting Memory does not know your account's opt-out setting.\n\n"
    "Official sources verified 2026-10-27."
)
DATA_BOUNDARIES = (
    "Local runs speech recognition and speaker diarization on this Mac. "
    "Preparing models downloads weights from Hugging Face without sending meeting content. "
    "Backblaze B2 Backup still sends audio and transcripts. When enabled, Notes and "
    "speaker suggestions send transcript text and relevant context to Anthropic. "
    "Saving changes pauses new transcription jobs until you quit and reopen the app."
)
_ENABLEMENT = (True, False)
_PROVIDERS = (TranscriptionProvider.LOCAL, TranscriptionProvider.ASSEMBLYAI)
_TARGET_CLASS = None


def transcription_change(view, enabled, provider, api_key, external_confirmed):
    from meeting_memory.ui.configuration_forms import configuration_change

    if (
        provider is TranscriptionProvider.ASSEMBLYAI
        and enabled is not False
        and not external_confirmed
    ):
        return None
    values = {field.key: field.value.value for field in view.fields}
    values[SettingKey.TRANSCRIPTION_PROVIDER] = provider.value
    if external_confirmed and provider is TranscriptionProvider.ASSEMBLYAI:
        values[SettingKey.ASSEMBLYAI_CONSENT] = ASSEMBLYAI_CONSENT_VERSION
    if provider is TranscriptionProvider.ASSEMBLYAI and enabled is not False:
        values[SettingKey.ASSEMBLYAI_API_KEY] = api_key
    return configuration_change(
        view,
        False if enabled is False else True,
        values,
        enabled is not False or external_confirmed,
    )


def open_transcription_form(view):
    from AppKit import NSAlert, NSMakeRect, NSPopUpButton, NSSecureTextField, NSView

    from meeting_memory.ui.configuration_forms import _label, _secret_placeholder, source_status

    panel = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 680, 260))
    enabled = NSPopUpButton.alloc().initWithFrame_pullsDown_(NSMakeRect(220, 218, 440, 28), False)
    enabled.addItemsWithTitles_(["Enabled (app-managed)", "Disabled"])
    enabled.selectItemAtIndex_(1 if view.preference is False else 0)
    provider = NSPopUpButton.alloc().initWithFrame_pullsDown_(NSMakeRect(220, 174, 440, 28), False)
    provider.addItemsWithTitles_(["Local (Apple Silicon)", "AssemblyAI (external)"])
    current = next(
        field.value.value for field in view.fields if field.key is SettingKey.TRANSCRIPTION_PROVIDER
    )
    provider.selectItemAtIndex_(1 if current == "assemblyai" else 0)
    key = NSSecureTextField.alloc().initWithFrame_(NSMakeRect(220, 130, 440, 26))
    key.setStringValue_("")
    key.setPlaceholderString_(_secret_placeholder(view.secret_availability))
    for title, y, control in (
        ("App preference", 222, enabled),
        ("Transcription provider", 178, provider),
        ("AssemblyAI key (external only)", 134, key),
    ):
        panel.addSubview_(_label(title, 0, y, 210, 22))
        panel.addSubview_(control)
    details = _label(DATA_BOUNDARIES, 0, 0, 670, 112)
    details.cell().setWraps_(True)
    details.cell().setScrollable_(False)
    details.setSelectable_(True)
    panel.addSubview_(details)
    target = _selection_target().alloc().init()
    target.key_control = key
    target.provider_control = provider
    target.enabled_control = enabled
    enabled.setTarget_(target)
    enabled.setAction_("providerChanged:")
    provider.setTarget_(target)
    provider.setAction_("providerChanged:")
    target.providerChanged_(provider)
    alert = NSAlert.alloc().init()
    alert.setMessageText_("Transcription")
    alert.setInformativeText_(
        source_status(view).replace(
            "Only app-owned values are shown. Secret fields always reopen blank.",
            "Saved app settings are shown here. Stored API keys stay hidden.",
        )
    )
    alert.setAccessoryView_(panel)
    alert.addButtonWithTitle_("Save")
    alert.addButtonWithTitle_("Cancel")
    if run_modal(alert) not in {1, 1000}:
        return None
    selected = _PROVIDERS[int(provider.indexOfSelectedItem())]
    preference = _ENABLEMENT[int(enabled.indexOfSelectedItem())]
    external_confirmed = False
    if selected is TranscriptionProvider.ASSEMBLYAI and preference is not False:
        external_confirmed = confirm_external_processing()
        if not external_confirmed:
            return None
    return transcription_change(
        view, preference, selected, str(key.stringValue()), external_confirmed
    )


def confirm_external_processing() -> bool:
    from AppKit import NSAlert, NSMakeRect, NSTextView

    alert = NSAlert.alloc().init()
    alert.setMessageText_("Send meeting audio to AssemblyAI?")
    alert.setInformativeText_(ASSEMBLYAI_NOTICE)
    sources = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, 620, 90))
    sources.setString_("\n".join(f"{title}: {url}" for title, url in OFFICIAL_SOURCES))
    sources.setEditable_(False)
    sources.setSelectable_(True)
    sources.checkTextInDocument_(None)
    alert.setAccessoryView_(sources)
    alert.addButtonWithTitle_("Accept & Save")
    alert.addButtonWithTitle_("Cancel")
    return run_modal(alert) in {1, 1000}


def _selection_target():
    global _TARGET_CLASS
    if _TARGET_CLASS is None:
        from Foundation import NSObject

        class TranscriptionProviderSelection(NSObject):
            def providerChanged_(self, sender):
                enabled = int(self.enabled_control.indexOfSelectedItem()) == 0
                self.provider_control.setEnabled_(enabled)
                self.key_control.setEnabled_(
                    enabled and int(self.provider_control.indexOfSelectedItem()) == 1
                )

        _TARGET_CLASS = TranscriptionProviderSelection
    return _TARGET_CLASS

"""Standard AppKit forms for app-owned capability configuration."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from meeting_memory.config.settings import Settings
from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration import (
    SecretBundle,
    SecretId,
    SecretValue,
    SettingKey,
)
from meeting_memory.types.configuration_editing import (
    CapabilityConfiguration,
    ConfigurationChange,
    ConfigurationField,
    ConfigurationValue,
    SecretAvailability,
)
from meeting_memory.ui.preference_forms import open_known_speakers_form

OK_RESPONSES = {1, 1000}
_ENABLEMENT = (None, True, False)
_SECRET_KEYS = {
    Capability.TRANSCRIPTION: (SettingKey.ASSEMBLYAI_API_KEY,),
    Capability.BACKUP: (
        SettingKey.B2_APPLICATION_KEY_ID,
        SettingKey.B2_APPLICATION_KEY,
    ),
    Capability.NOTES: (SettingKey.ANTHROPIC_API_KEY,),
}
_SECRET_IDS = {
    Capability.TRANSCRIPTION: SecretId.TRANSCRIPTION,
    Capability.BACKUP: SecretId.BACKUP,
    Capability.NOTES: SecretId.NOTES,
}
FIELD_LABELS = {
    SettingKey.MEETINGS_DIR: "Meetings folder",
    SettingKey.MAX_RECORDING_MINUTES: "Recording limit (minutes)",
    SettingKey.ASSEMBLYAI_API_KEY: "AssemblyAI API key",
    SettingKey.B2_APPLICATION_KEY_ID: "B2 application key ID",
    SettingKey.B2_APPLICATION_KEY: "B2 application key",
    SettingKey.B2_ENDPOINT: "B2 S3 endpoint",
    SettingKey.B2_REGION: "B2 region",
    SettingKey.B2_BUCKET_NAME: "B2 bucket",
    SettingKey.GOOGLE_CALENDAR_CREDENTIALS_FILE: "OAuth credentials file",
    SettingKey.GOOGLE_CALENDAR_ID: "Calendar ID",
    SettingKey.KNOWN_SPEAKERS: "Known speakers (JSON)",
    SettingKey.NOTIFY_MINUTES_BEFORE: "Reminder (minutes)",
    SettingKey.CALENDAR_POLL_INTERVAL: "Polling interval (seconds)",
    SettingKey.ANTHROPIC_API_KEY: "Anthropic API key",
    SettingKey.ANTHROPIC_MODEL: "Anthropic model",
    SettingKey.SUMMARY_PROMPT_FILE: "Notes instructions and layout file",
}
DISCLOSURES = {
    Capability.TRANSCRIPTION: (
        "AssemblyAI receives each newly committed meeting audio file automatically "
        "after recording stops, and returns a diarized transcript."
    ),
    Capability.BACKUP: (
        "Backblaze B2 receives recording.m4a and transcript.md automatically for "
        "new eligible meetings. Notes and historical meetings are not uploaded."
    ),
    Capability.CALENDAR: (
        "A browser opens for OAuth only after the explicit Authorize action. After "
        "authorization and restart, read-only Google Calendar API polling runs "
        "automatically while enabled; event metadata and attendees are received locally."
    ),
    Capability.NOTES: (
        "Anthropic receives the fixed output-schema instructions, the instruction block, "
        "and only a speaker-confirmed transcript excerpt capped at 60,000 characters. "
        "The editable Markdown layout stays local. Notes generation starts after explicit "
        "speaker confirmation."
    ),
}


def open_configuration_form(view: CapabilityConfiguration) -> ConfigurationChange | None:
    """Render one native form; secret controls are always blank and secure."""

    from AppKit import (
        NSAlert,
        NSMakeRect,
        NSPopUpButton,
        NSSecureTextField,
        NSTextField,
        NSView,
    )

    rows = len(view.fields) + len(_SECRET_KEYS.get(view.capability, ()))
    enablement_height = 44 if view.capability is not Capability.RECORDING_CORE else 0
    width, row_height = 720, 42
    height = 42 + enablement_height + rows * row_height
    panel = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))
    controls: dict[SettingKey, Any] = {}
    fixed_values: dict[SettingKey, str] = {}
    popup = None
    y = height - 32
    if view.capability is not Capability.RECORDING_CORE:
        popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(220, y - 4, 480, 26), False
        )
        popup.addItemsWithTitles_(
            ["Keep compatibility settings", "Enabled (app-managed)", "Disabled"]
        )
        popup.selectItemAtIndex_(_ENABLEMENT.index(view.preference))
        panel.addSubview_(_label("App preference", 0, y, 205, 22))
        panel.addSubview_(popup)
        y -= enablement_height
    for field in view.fields:
        if field.key is SettingKey.KNOWN_SPEAKERS:
            speakers = Settings.parse_known_speakers(field.value.value)
            panel.addSubview_(_label(FIELD_LABELS[field.key], 0, y, 205, 22))
            panel.addSubview_(
                _label(
                    f"{len(speakers)} configured · structured editor opens after Save",
                    220,
                    y,
                    480,
                    22,
                )
            )
            fixed_values[field.key] = field.value.value
            y -= row_height
            continue
        control = NSTextField.alloc().initWithFrame_(NSMakeRect(220, y - 4, 480, 24))
        control.setStringValue_(field.value.value)
        panel.addSubview_(_label(FIELD_LABELS[field.key], 0, y, 205, 22))
        panel.addSubview_(control)
        controls[field.key] = control
        y -= row_height
    for key in _SECRET_KEYS.get(view.capability, ()):
        control = NSSecureTextField.alloc().initWithFrame_(NSMakeRect(220, y - 4, 480, 24))
        control.setStringValue_("")
        control.setPlaceholderString_(_secret_placeholder(view.secret_availability))
        panel.addSubview_(_label(FIELD_LABELS[key], 0, y, 205, 22))
        panel.addSubview_(control)
        controls[key] = control
        y -= row_height
    alert = NSAlert.alloc().init()
    alert.setMessageText_(view.capability.label)
    alert.setInformativeText_(source_status(view))
    alert.addButtonWithTitle_("Save")
    alert.addButtonWithTitle_("Cancel")
    alert.setAccessoryView_(panel)
    if int(alert.runModal()) not in OK_RESPONSES:
        return None
    enabled = None if popup is None else _ENABLEMENT[int(popup.indexOfSelectedItem())]
    disclosure = not requires_disclosure(view, enabled) or confirm_disclosure(view.capability)
    if not disclosure:
        return None
    values = {key: str(control.stringValue()) for key, control in controls.items()}
    values.update(fixed_values)
    if view.capability is Capability.CALENDAR:
        current = Settings.parse_known_speakers(values[SettingKey.KNOWN_SPEAKERS])
        speakers = open_known_speakers_form(current)
        if speakers is not None:
            values[SettingKey.KNOWN_SPEAKERS] = _known_speakers_value(speakers)
    return configuration_change(view, enabled, values, disclosure)


def configuration_change(
    view: CapabilityConfiguration,
    enabled: bool | None,
    values: Mapping[SettingKey, str],
    disclosure_confirmed: bool,
) -> ConfigurationChange:
    fields = tuple(
        ConfigurationField(field.key, ConfigurationValue(values[field.key]))
        for field in view.fields
    )
    secret = _secret_bundle(view.capability, values)
    return ConfigurationChange(
        view.edit_id,
        view.capability,
        enabled,
        fields,
        secret,
        disclosure_confirmed=disclosure_confirmed,
    )


def requires_disclosure(view: CapabilityConfiguration, enabled: bool | None) -> bool:
    return enabled is True or (view.preference is False and enabled is None)


def source_status(view: CapabilityConfiguration) -> str:
    messages = ["Only app-owned values are shown. Secret fields always reopen blank."]
    if view.legacy_active:
        messages.append("Using legacy .env compatibility settings.")
    if view.process_present:
        messages.append("Process environment values override part of this form.")
    if view.process_reenables:
        messages.append("Process environment settings will re-enable this after restart.")
    if view.legacy_reenables:
        messages.append("Keeping compatibility settings may re-enable the legacy setup.")
    return "\n".join(messages)


def confirm_disclosure(capability: Capability) -> bool:
    from AppKit import NSAlert

    alert = NSAlert.alloc().init()
    alert.setMessageText_(f"Enable {capability.label}?")
    alert.setInformativeText_(DISCLOSURES[capability])
    alert.addButtonWithTitle_("Save & Enable")
    alert.addButtonWithTitle_("Cancel")
    return int(alert.runModal()) in OK_RESPONSES


def _secret_bundle(capability: Capability, values: Mapping[SettingKey, str]) -> SecretBundle | None:
    keys = _SECRET_KEYS.get(capability, ())
    if not keys:
        return None
    raw = tuple(str(values.get(key, "")).strip() for key in keys)
    if not any(raw):
        return None
    if not all(raw):
        raise ValueError("Every credential field must be completed together.")
    return SecretBundle(
        _SECRET_IDS[capability],
        tuple(SecretValue(key, value) for key, value in zip(keys, raw, strict=True)),
    )


def _secret_placeholder(availability: SecretAvailability) -> str:
    if availability is SecretAvailability.AVAILABLE:
        return "Stored in Keychain — leave blank to keep"
    return "Enter a new credential"


def _known_speakers_value(speakers) -> str:
    return json.dumps(
        [{"name": speaker.name, "matches": list(speaker.matches)} for speaker in speakers],
        separators=(",", ":"),
    )


def _label(text: str, x: int, y: int, width: int, height: int):
    from AppKit import NSMakeRect, NSTextField

    field = NSTextField.alloc().initWithFrame_(NSMakeRect(x, y, width, height))
    field.setStringValue_(text)
    field.setBezeled_(False)
    field.setDrawsBackground_(False)
    field.setEditable_(False)
    field.setSelectable_(False)
    return field

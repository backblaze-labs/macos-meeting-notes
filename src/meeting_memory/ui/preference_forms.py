"""Native macOS preference forms."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from meeting_memory.types.speakers import KnownSpeaker

OK_RESPONSES = {1, 1000}
KNOWN_SPEAKERS_BLANK_ROWS = 3


@dataclass(frozen=True)
class PreferenceFormField:
    key: str
    label: str
    value: str
    guidance: str


def open_preferences_form(fields: tuple[PreferenceFormField, ...]) -> dict[str, str] | None:
    from AppKit import NSAlert, NSMakeRect, NSTextField, NSView

    width = 720
    row_height = 64
    height = 42 + len(fields) * row_height
    view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))
    rows: list[tuple[str, Any]] = []

    for index, field in enumerate(fields):
        y = height - 32 - index * row_height
        value_field = NSTextField.alloc().initWithFrame_(NSMakeRect(178, y - 3, 512, 24))
        value_field.setStringValue_(field.value)

        view.addSubview_(_label_field(field.label, 0, y, 166, 22))
        view.addSubview_(value_field)
        view.addSubview_(_hint_field(field.guidance, 178, y - 35, 512, 28))
        rows.append((field.key, value_field))

    alert = NSAlert.alloc().init()
    alert.setMessageText_("Meeting Memory Preferences")
    alert.setInformativeText_("Edit values, save, then restart Meeting Memory.")
    alert.addButtonWithTitle_("Save")
    alert.addButtonWithTitle_("Cancel")
    alert.setAccessoryView_(view)
    if not _is_ok_response(alert.runModal()):
        return None
    return {key: str(value.stringValue()).strip() for key, value in rows}


def open_known_speakers_form(
    speakers: tuple[KnownSpeaker, ...],
) -> tuple[KnownSpeaker, ...] | None:
    from AppKit import NSAlert, NSMakeRect, NSTextField, NSView

    row_values = list(speakers)
    blank_rows = max(KNOWN_SPEAKERS_BLANK_ROWS, 1 if not speakers else 0)
    width = 720
    row_height = 34
    height = 104 + (len(row_values) + blank_rows) * row_height
    view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))
    rows: list[tuple[Any, Any]] = []

    header_y = height - 30
    view.addSubview_(_label_field("Alias to show", 0, header_y, 190, 22))
    view.addSubview_(_label_field("Calendar attendee to match", 216, header_y, 474, 22))

    for index in range(len(row_values) + blank_rows):
        speaker = row_values[index] if index < len(row_values) else None
        y = header_y - 36 - index * row_height
        alias_field = NSTextField.alloc().initWithFrame_(NSMakeRect(0, y - 3, 190, 24))
        source_field = NSTextField.alloc().initWithFrame_(NSMakeRect(216, y - 3, 474, 24))
        alias_field.setPlaceholderString_("Alex Rivera")
        source_field.setPlaceholderString_("alex@example.com, alex.rivera")
        if speaker is not None:
            alias_field.setStringValue_(speaker.name)
            source_field.setStringValue_(", ".join(speaker.matches))
        view.addSubview_(alias_field)
        view.addSubview_(source_field)
        rows.append((alias_field, source_field))

    view.addSubview_(
        _hint_field(
            (
                "This only cleans up speaker suggestions. Alias is the name you want shown. "
                "Match can be an invite email, email username, or Calendar display name."
            ),
            0,
            8,
            690,
            40,
        )
    )

    alert = NSAlert.alloc().init()
    alert.setMessageText_("Known Speakers")
    alert.setInformativeText_("Leave Alias blank to remove a row. Add people on blank rows.")
    alert.addButtonWithTitle_("Save")
    alert.addButtonWithTitle_("Cancel")
    alert.setAccessoryView_(view)
    if not _is_ok_response(alert.runModal()):
        return None
    return speakers_from_form_rows(
        (str(alias.stringValue()), str(source.stringValue())) for alias, source in rows
    )


def speakers_from_form_rows(rows: Any) -> tuple[KnownSpeaker, ...]:
    speakers: list[KnownSpeaker] = []
    seen: set[str] = set()
    for raw_alias, raw_sources in rows:
        alias = str(raw_alias).strip()
        if not alias:
            continue
        key = alias.casefold()
        if key in seen:
            continue
        speakers.append(KnownSpeaker(alias, _split_sources(str(raw_sources))))
        seen.add(key)
    return tuple(speakers)


def _split_sources(raw_sources: str) -> tuple[str, ...]:
    return tuple(source.strip() for source in raw_sources.split(",") if source.strip())


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
    field.setFont_(NSFont.systemFontOfSize_(11))
    return field


def _is_ok_response(response: object) -> bool:
    try:
        return int(response) in OK_RESPONSES
    except (TypeError, ValueError):
        return bool(response)

"""Native confirmation surfaces for legacy migration and Calendar OAuth."""

from __future__ import annotations

from typing import Any

from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration_migration import (
    MigrationConfirmation,
    MigrationPreview,
    MigrationPreviewState,
)
from meeting_memory.ui.configuration_forms import DISCLOSURES, OK_RESPONSES


def open_migration_preview(preview: MigrationPreview) -> MigrationConfirmation | None:
    if preview.state is not MigrationPreviewState.READY:
        return None
    from AppKit import NSAlert, NSButton, NSMakeRect, NSView

    candidates = preview.candidates
    heights = tuple(34 + len(candidate.fields) * 17 for candidate in candidates)
    height = 54 + sum(heights)
    panel = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 680, height))
    controls: list[tuple[Capability, Any]] = []
    y = height - 38
    for candidate, row_height in zip(candidates, heights, strict=True):
        button = NSButton.alloc().initWithFrame_(NSMakeRect(0, y, 660, 24))
        button.setButtonType_(3)
        button.setTitle_(candidate.capability.label)
        button.setState_(0)
        button.setEnabled_(candidate.selectable)
        panel.addSubview_(button)
        panel.addSubview_(_detail(candidate, y - row_height + 8, row_height - 28))
        controls.append((candidate.capability, button))
        y -= row_height
    alert = NSAlert.alloc().init()
    alert.setMessageText_("Import Legacy Configuration")
    alert.setInformativeText_(
        "Choose whole capabilities to import. Nothing is selected by default. "
        "The legacy .env file will not be changed or deleted. Process values are not "
        "imported and remain higher-priority overrides."
    )
    alert.addButtonWithTitle_("Review Selection")
    alert.addButtonWithTitle_("Cancel")
    alert.setAccessoryView_(panel)
    if int(alert.runModal()) not in OK_RESPONSES:
        return None
    selected = tuple(
        capability
        for capability, control in controls
        if control.isEnabled() and int(control.state()) == 1
    )
    if not selected or not _confirm_migration(selected):
        return None
    return MigrationConfirmation(preview.preview_id, selected, True)


def confirm_calendar_authorization() -> bool:
    from AppKit import NSAlert

    alert = NSAlert.alloc().init()
    alert.setMessageText_("Authorize Google Calendar?")
    alert.setInformativeText_(
        f"{DISCLOSURES[Capability.CALENDAR]}\n\n"
        "A browser window opens only for this explicit action. Meeting Memory stores "
        "the OAuth token in macOS Keychain and does not query Calendar during authorization."
    )
    alert.addButtonWithTitle_("Open Browser")
    alert.addButtonWithTitle_("Cancel")
    return int(alert.runModal()) in OK_RESPONSES


def _confirm_migration(selected: tuple[Capability, ...]) -> bool:
    from AppKit import NSAlert

    optional = tuple(
        capability for capability in selected if capability is not Capability.RECORDING_CORE
    )
    disclosure = "\n\n".join(DISCLOSURES[capability] for capability in optional)
    capabilities = ", ".join(capability.label for capability in selected)
    alert = NSAlert.alloc().init()
    alert.setMessageText_("Confirm Legacy Import")
    alert.setInformativeText_(
        f"Import: {capabilities}.\n\n{disclosure}\n\n"
        "Only the selected settings are copied to app-owned preferences and Keychain. "
        "The .env file remains byte-identical."
    )
    alert.addButtonWithTitle_("Import Selected")
    alert.addButtonWithTitle_("Cancel")
    return int(alert.runModal()) in OK_RESPONSES


def migration_detail(candidate) -> str:
    rows = []
    for field in candidate.fields:
        flags = []
        if field.secret:
            flags.append("credential")
        if field.process_present:
            flags.append("process override present")
        suffix = f" · {', '.join(flags)}" if flags else ""
        rows.append(f"{field.key.value} — {field.state.value}{suffix}")
    return "\n".join(rows)


def _detail(candidate, y: int, height: int):
    from AppKit import NSFont, NSMakeRect, NSTextField

    field = NSTextField.alloc().initWithFrame_(NSMakeRect(24, y, 636, height))
    field.setStringValue_(migration_detail(candidate))
    field.setFont_(NSFont.systemFontOfSize_(11))
    field.setBezeled_(False)
    field.setDrawsBackground_(False)
    field.setEditable_(False)
    field.setSelectable_(False)
    return field

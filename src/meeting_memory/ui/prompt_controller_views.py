"""View synchronization and wiring for the Notes profile controller."""

from __future__ import annotations

from typing import Any

from meeting_memory.types.notes_profile import (
    NotesProfile,
    NotesProfileKind,
    NotesSectionAudience,
    NotesSectionFormat,
)
from meeting_memory.ui.prompt_preview import update_notes_profile_preview
from meeting_memory.ui.prompt_widgets import bind

AUDIENCES = tuple(NotesSectionAudience)
FORMATS = tuple(NotesSectionFormat)


def apply_profile(controller: Any, profile: NotesProfile) -> None:
    from AppKit import NSControlStateValueOff, NSControlStateValueOn

    controller._syncing = True
    controller._profile = profile
    classic = profile.kind is NotesProfileKind.CLASSIC
    personal = profile.kind is NotesProfileKind.PERSONAL
    controller._views.templates.classic.setState_(
        NSControlStateValueOn if classic else NSControlStateValueOff
    )
    controller._views.templates.personal.setState_(
        NSControlStateValueOn if personal else NSControlStateValueOff
    )
    for control in (
        controller._views.templates.user_name,
        controller._views.templates.user_name_label,
        controller._views.templates.user_name_help,
    ):
        control.setHidden_(not personal)
    variable = profile.variable_for("user_name")
    name = "" if variable is None else variable.value
    controller._views.templates.user_name.setStringValue_(name)
    controller._views.advanced.user_name.setStringValue_(name)
    controller._views.advanced.report_title.setStringValue_(profile.report_title)
    controller._views.advanced.instructions.setString_(controller._instructions)
    controller._views.advanced.include_source.setState_(int(profile.include_source))
    controller._views.advanced.include_date.setState_(int(profile.include_date))
    reload_section_menu(controller)
    sync_section_controls(controller)
    controller._syncing = False
    refresh_previews(controller)
    controller._hide_error()


def reload_section_menu(controller: Any) -> None:
    menu = controller._views.advanced.section_selector
    menu.removeAllItems()
    menu.addItemsWithTitles_(tuple(section.title for section in controller._profile.sections))
    menu.selectItemAtIndex_(controller._selected_section)


def sync_section_controls(controller: Any) -> None:
    section = controller._profile.sections[controller._selected_section]
    views = controller._views.advanced
    views.section_title.setStringValue_(section.title)
    views.guidance.setString_(section.instructions)
    views.audience.selectItemAtIndex_(AUDIENCES.index(section.audience))
    views.output_format.selectItemAtIndex_(FORMATS.index(section.output_format))
    views.remove_section.setEnabled_(len(controller._profile.sections) > 1)
    views.add_section.setEnabled_(len(controller._profile.sections) < 8)
    views.move_up.setEnabled_(controller._selected_section > 0)
    views.move_down.setEnabled_(
        controller._selected_section < len(controller._profile.sections) - 1
    )


def refresh_previews(controller: Any) -> None:
    for preview in (controller._views.templates.preview, controller._views.advanced.preview):
        update_notes_profile_preview(preview, controller._profile)


def wire_controls(controller: Any) -> None:
    views = controller._views
    bind(views.page_selector, controller, "switchPage:")
    bind(views.templates.classic, controller, "chooseClassic:")
    bind(views.templates.personal, controller, "choosePersonal:")
    bind(views.templates.customize, controller, "customizeTemplate:")
    bind(views.advanced.section_selector, controller, "sectionChanged:")
    bind(views.advanced.add_section, controller, "addSection:")
    bind(views.advanced.remove_section, controller, "removeSection:")
    views.advanced.move_up.setTag_(-1)
    views.advanced.move_down.setTag_(1)
    bind(views.advanced.move_up, controller, "moveSection:")
    bind(views.advanced.move_down, controller, "moveSection:")
    for control in (
        views.advanced.audience,
        views.advanced.output_format,
        views.advanced.include_source,
        views.advanced.include_date,
    ):
        bind(control, controller, "profileOptionChanged:")
    bind(views.restore, controller, "restoreDefaults:")
    bind(views.cancel, controller, "cancelChanges:")
    bind(views.save, controller, "saveChanges:")
    for control in (
        views.templates.user_name,
        views.advanced.user_name,
        views.advanced.report_title,
        views.advanced.section_title,
    ):
        control.setDelegate_(controller)
    views.advanced.guidance.setDelegate_(controller)
    views.advanced.instructions.setDelegate_(controller)

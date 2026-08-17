"""Controller for template selection and advanced Notes profile editing."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from meeting_memory.config.notes_profiles import (
    default_profile_instructions,
    validate_notes_profile_ready,
)
from meeting_memory.config.notes_template import compose_notes_profile_document
from meeting_memory.types.configuration_surface import PromptDraft
from meeting_memory.types.notes_profile import NotesProfile, NotesProfileKind
from meeting_memory.ui.prompt_controller_views import (
    AUDIENCES,
    FORMATS,
    apply_profile,
    refresh_previews,
    sync_section_controls,
    wire_controls,
)
from meeting_memory.ui.prompt_profile_editing import (
    add_section,
    move_section,
    remove_section,
    replace_section,
    select_template,
)
from meeting_memory.ui.prompt_profile_state import custom_profile, with_user_name
from meeting_memory.ui.prompt_window import PromptWindowViews

_CONTROLLER_CLASS: Any | None = None


def create_prompt_controller(
    profile: NotesProfile,
    instructions: str,
    views: PromptWindowViews,
) -> Any:
    controller = _controller_class().alloc().init()
    controller.configure(profile, instructions, views)
    return controller


def _controller_class() -> Any:
    global _CONTROLLER_CLASS
    if _CONTROLLER_CLASS is not None:
        return _CONTROLLER_CLASS

    import objc
    from Foundation import NSObject

    class NotesCustomizationController(NSObject):
        @objc.python_method
        def configure(
            self,
            profile: NotesProfile,
            instructions: str,
            views: PromptWindowViews,
        ) -> None:
            self._profile = profile
            self._instructions = instructions
            self._views = views
            self._selected_section = 0
            self._result = None
            self._syncing = False
            wire_controls(self)
            apply_profile(self, profile)
            views.window.setDelegate_(self)

        @objc.python_method
        def run(self) -> PromptDraft | None:
            from AppKit import NSApplication

            app = NSApplication.sharedApplication()
            self._views.window.makeKeyAndOrderFront_(None)
            app.activateIgnoringOtherApps_(True)
            app.runModalForWindow_(self._views.window)
            self._views.window.orderOut_(None)
            return self._result

        def switchPage_(self, _sender: Any) -> None:
            templates = self._views.page_selector.selectedSegment() == 0
            self._views.templates.page.setHidden_(not templates)
            self._views.advanced.page.setHidden_(templates)
            self._hide_error()

        def customizeTemplate_(self, _sender: Any) -> None:
            self._views.page_selector.setSelectedSegment_(1)
            self.switchPage_(None)

        def chooseClassic_(self, _sender: Any) -> None:
            self._choose_template(NotesProfileKind.CLASSIC)

        def choosePersonal_(self, _sender: Any) -> None:
            name = str(self._views.templates.user_name.stringValue())
            self._choose_template(NotesProfileKind.PERSONAL, user_name=name)

        def sectionChanged_(self, _sender: Any) -> None:
            self._commit_section(show_error=False)
            self._selected_section = int(
                self._views.advanced.section_selector.indexOfSelectedItem()
            )
            sync_section_controls(self)
            self._hide_error()

        def addSection_(self, _sender: Any) -> None:
            self._commit_section(show_error=False)
            try:
                self._profile, self._selected_section = add_section(self._profile)
            except ValueError as exc:
                self._show_error(str(exc))
                return
            apply_profile(self, self._profile)

        def removeSection_(self, _sender: Any) -> None:
            self._profile, self._selected_section = remove_section(
                self._profile, self._selected_section
            )
            apply_profile(self, self._profile)

        def moveSection_(self, sender: Any) -> None:
            self._commit_section(show_error=False)
            shift = -1 if int(sender.tag()) == -1 else 1
            self._profile, self._selected_section = move_section(
                self._profile, self._selected_section, shift
            )
            apply_profile(self, self._profile)

        def profileOptionChanged_(self, _sender: Any) -> None:
            if self._syncing:
                return
            try:
                updated = replace(
                    self._profile,
                    include_source=bool(self._views.advanced.include_source.state()),
                    include_date=bool(self._views.advanced.include_date.state()),
                )
                self._profile = custom_profile(updated)
                self._commit_section(show_error=False)
            except ValueError:
                return
            refresh_previews(self)

        def controlTextDidChange_(self, notification: Any) -> None:
            if self._syncing:
                return
            control = notification.object()
            try:
                if control is self._views.templates.user_name:
                    self._profile = with_user_name(self._profile, str(control.stringValue()))
                    self._views.advanced.user_name.setStringValue_(str(control.stringValue()))
                elif control is self._views.advanced.user_name:
                    self._profile = custom_profile(
                        with_user_name(self._profile, str(control.stringValue()))
                    )
                    self._views.templates.user_name.setStringValue_(str(control.stringValue()))
                elif control is self._views.advanced.report_title:
                    self._profile = custom_profile(
                        replace(self._profile, report_title=str(control.stringValue()))
                    )
                elif control is self._views.advanced.section_title:
                    self._commit_section(show_error=False)
            except ValueError:
                return
            refresh_previews(self)

        def textDidChange_(self, notification: Any) -> None:
            if self._syncing:
                return
            control = notification.object()
            if control is self._views.advanced.guidance:
                self._commit_section(show_error=False)
            elif control is self._views.advanced.instructions:
                self._instructions = str(control.string())
            self._hide_error()

        def restoreDefaults_(self, _sender: Any) -> None:
            self._instructions = default_profile_instructions()
            self._profile = select_template(NotesProfileKind.CLASSIC)
            self._selected_section = 0
            self._views.page_selector.setSelectedSegment_(0)
            self.switchPage_(None)
            apply_profile(self, self._profile)

        def saveChanges_(self, _sender: Any) -> None:
            try:
                self._commit_all_controls()
                validate_notes_profile_ready(self._profile)
                instructions = str(self._views.advanced.instructions.string()).strip()
                if not instructions:
                    raise ValueError("General AI guidance cannot be empty.")
                combined = compose_notes_profile_document(instructions, self._profile)
            except ValueError as exc:
                self._show_error(_validation_message(exc))
                return
            self._result = PromptDraft(combined)
            self._finish_modal()

        def cancelChanges_(self, _sender: Any) -> None:
            self._result = None
            self._finish_modal()

        def windowShouldClose_(self, _sender: Any) -> bool:
            self._result = None
            self._finish_modal()
            return False

        @objc.python_method
        def _choose_template(self, kind: NotesProfileKind, *, user_name: str = "") -> None:
            self._instructions = default_profile_instructions()
            self._profile = select_template(kind, user_name=user_name)
            self._selected_section = 0
            apply_profile(self, self._profile)

        @objc.python_method
        def _commit_all_controls(self) -> None:
            self._profile = replace(
                self._profile,
                report_title=str(self._views.advanced.report_title.stringValue()).strip(),
                include_source=bool(self._views.advanced.include_source.state()),
                include_date=bool(self._views.advanced.include_date.state()),
            )
            name_control = (
                self._views.templates.user_name
                if self._profile.kind is NotesProfileKind.PERSONAL
                else self._views.advanced.user_name
            )
            self._profile = with_user_name(self._profile, str(name_control.stringValue()))
            self._commit_section(show_error=True)

        @objc.python_method
        def _commit_section(self, *, show_error: bool) -> None:
            try:
                self._profile = replace_section(
                    self._profile,
                    self._selected_section,
                    title=str(self._views.advanced.section_title.stringValue()).strip(),
                    instructions=str(self._views.advanced.guidance.string()).strip(),
                    audience=AUDIENCES[int(self._views.advanced.audience.indexOfSelectedItem())],
                    output_format=FORMATS[
                        int(self._views.advanced.output_format.indexOfSelectedItem())
                    ],
                )
            except ValueError as exc:
                if show_error:
                    raise
                self._show_error(str(exc))

        @objc.python_method
        def _show_error(self, message: str) -> None:
            self._views.error.setStringValue_(message)
            self._views.error.setHidden_(False)

        @objc.python_method
        def _hide_error(self) -> None:
            self._views.error.setHidden_(True)

        @objc.python_method
        def _finish_modal(self) -> None:
            from AppKit import NSApplication

            NSApplication.sharedApplication().abortModal()

    _CONTROLLER_CLASS = NotesCustomizationController
    return _CONTROLLER_CLASS


def _validation_message(error: ValueError) -> str:
    message = str(error)
    if "required template field" in message:
        return "Enter your name before saving this template."
    if "section titles" in message:
        return "Give every section a short, single-line title."
    if "generation guidance" in message:
        return "Describe what the selected section should capture."
    if "unknown template fields" in message:
        return "This section uses a template field that is not configured."
    if "layout marker" in message or "profile marker" in message:
        return "Remove Meeting Memory's private storage separators before saving."
    if "missing required placeholders" in message:
        return "The generated profile layout is incomplete. Restore Classic and try again."
    return message

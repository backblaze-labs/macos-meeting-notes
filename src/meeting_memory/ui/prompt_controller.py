"""Target/action controller for the native Notes customization workspace."""

from __future__ import annotations

from typing import Any

from meeting_memory.config.notes_template import (
    NotesPromptDocument,
    NotesVisualLayout,
    NotesVisualSection,
    compose_notes_prompt_document,
    default_notes_prompt_document,
    parse_visual_notes_layout,
    render_visual_notes_layout,
)
from meeting_memory.types.configuration_surface import PromptDraft
from meeting_memory.ui.prompt_layout_rows import placeholder_visual_layout
from meeting_memory.ui.prompt_preview import update_notes_preview
from meeting_memory.ui.prompt_widgets import bind
from meeting_memory.ui.prompt_window import PromptWindowViews

_CONTROLLER_CLASS: Any | None = None


def create_prompt_controller(
    document: NotesPromptDocument,
    visual_layout: NotesVisualLayout | None,
    views: PromptWindowViews,
) -> Any:
    controller = _controller_class().alloc().init()
    controller.configure(document, visual_layout, views)
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
            document: NotesPromptDocument,
            visual_layout: NotesVisualLayout | None,
            views: PromptWindowViews,
        ) -> None:
            self._views = views
            self._result = None
            self._advanced = visual_layout is None
            layout = visual_layout or placeholder_visual_layout()
            self._section_order = [section.key for section in layout.sections]
            self._wire_controls()
            self._apply_visual_layout(layout)
            self._show_advanced(self._advanced)
            views.instructions_editor.setString_(document.instructions)
            views.layout.advanced_editor.setString_(document.report_template)
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
            instructions = self._views.page_selector.selectedSegment() == 0
            self._views.instructions_page.setHidden_(not instructions)
            self._views.layout.page.setHidden_(instructions)
            self._hide_error()

        def visualChanged_(self, _sender: Any) -> None:
            self._hide_error()
            self._refresh_preview()

        def controlTextDidChange_(self, _notification: Any) -> None:
            self._hide_error()
            self._refresh_preview()

        def textDidChange_(self, _notification: Any) -> None:
            self._hide_error()

        def moveSection_(self, sender: Any) -> None:
            index = int(sender.tag()) // 2
            shift = -1 if int(sender.tag()) % 2 == 0 else 1
            destination = index + shift
            if destination < 0 or destination >= len(self._section_order):
                return
            headings = self._headings_by_key()
            self._section_order[index], self._section_order[destination] = (
                self._section_order[destination],
                self._section_order[index],
            )
            self._sync_section_rows(headings)
            self._refresh_preview()

        def openAdvanced_(self, _sender: Any) -> None:
            try:
                report_template = render_visual_notes_layout(self._layout_from_controls())
            except ValueError as exc:
                self._show_error(_validation_message(exc))
                return
            self._views.layout.advanced_editor.setString_(report_template)
            self._show_advanced(True)

        def closeAdvanced_(self, _sender: Any) -> None:
            report_template = str(self._views.layout.advanced_editor.string())
            try:
                layout = parse_visual_notes_layout(report_template)
            except ValueError as exc:
                self._show_error(_validation_message(exc))
                return
            if layout is None:
                self._show_error(
                    "This custom template cannot be represented visually. "
                    "Keep editing Markdown or restore the default layout."
                )
                return
            self._apply_visual_layout(layout)
            self._show_advanced(False)

        def restoreDefaults_(self, _sender: Any) -> None:
            document = default_notes_prompt_document()
            layout = parse_visual_notes_layout(document.report_template)
            if layout is None:
                return
            self._views.instructions_editor.setString_(document.instructions)
            self._views.layout.advanced_editor.setString_(document.report_template)
            self._apply_visual_layout(layout)
            self._show_advanced(False)
            self._hide_error()

        def saveChanges_(self, _sender: Any) -> None:
            instructions = str(self._views.instructions_editor.string()).strip()
            if not instructions:
                self._show_error("AI instructions cannot be empty.")
                return
            try:
                report_template = (
                    str(self._views.layout.advanced_editor.string())
                    if self._advanced
                    else render_visual_notes_layout(self._layout_from_controls())
                )
                combined = compose_notes_prompt_document(instructions, report_template)
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
        def _wire_controls(self) -> None:
            views = self._views
            bind(views.page_selector, self, "switchPage:")
            bind(views.restore, self, "restoreDefaults:")
            bind(views.cancel, self, "cancelChanges:")
            bind(views.save, self, "saveChanges:")
            bind(views.layout.include_source, self, "visualChanged:")
            bind(views.layout.include_date, self, "visualChanged:")
            bind(views.layout.open_advanced, self, "openAdvanced:")
            bind(views.layout.close_advanced, self, "closeAdvanced:")
            views.instructions_editor.setDelegate_(self)
            views.layout.advanced_editor.setDelegate_(self)
            views.layout.document_title.setDelegate_(self)
            for row in views.layout.sections:
                row.title.setDelegate_(self)
                bind(row.move_up, self, "moveSection:")
                bind(row.move_down, self, "moveSection:")

        @objc.python_method
        def _layout_from_controls(self) -> NotesVisualLayout:
            sections = tuple(
                NotesVisualSection(key, str(row.title.stringValue()).strip())
                for key, row in zip(
                    self._section_order,
                    self._views.layout.sections,
                    strict=True,
                )
            )
            return NotesVisualLayout(
                str(self._views.layout.document_title.stringValue()).strip(),
                sections,
                bool(self._views.layout.include_source.state()),
                bool(self._views.layout.include_date.state()),
            )

        @objc.python_method
        def _apply_visual_layout(self, layout: NotesVisualLayout) -> None:
            self._section_order = [section.key for section in layout.sections]
            self._views.layout.document_title.setStringValue_(layout.title)
            self._views.layout.include_source.setState_(int(layout.include_source))
            self._views.layout.include_date.setState_(int(layout.include_date))
            self._sync_section_rows(
                {section.key: section.heading for section in layout.sections}
            )
            self._refresh_preview()

        @objc.python_method
        def _sync_section_rows(self, headings: dict[str, str]) -> None:
            kinds = {
                "summary": "Generated summary",
                "decisions": "Generated decisions",
                "action_items": "Generated action items",
            }
            last = len(self._views.layout.sections) - 1
            for index, (key, row) in enumerate(
                zip(self._section_order, self._views.layout.sections, strict=True)
            ):
                row.title.setStringValue_(headings[key])
                row.kind.setStringValue_(kinds[key])
                row.move_up.setEnabled_(index > 0)
                row.move_down.setEnabled_(index < last)

        @objc.python_method
        def _headings_by_key(self) -> dict[str, str]:
            return {
                key: str(row.title.stringValue())
                for key, row in zip(
                    self._section_order,
                    self._views.layout.sections,
                    strict=True,
                )
            }

        @objc.python_method
        def _refresh_preview(self) -> None:
            update_notes_preview(self._views.layout.preview, self._layout_from_controls())

        @objc.python_method
        def _show_advanced(self, visible: bool) -> None:
            self._advanced = visible
            self._views.layout.visual.setHidden_(visible)
            self._views.layout.advanced.setHidden_(not visible)
            self._hide_error()

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
    if "unsupported placeholders" in message:
        return "Advanced Markdown uses an unsupported field. Use only the fields listed."
    if "missing required placeholders" in message:
        return "Include {summary}, {decisions}, and {action_items} before saving."
    if "layout marker" in message:
        return "Remove the app-owned separator from Advanced Markdown before saving."
    if "layout cannot be empty" in message:
        return "Advanced Markdown cannot be empty."
    return message

"""Main-thread-only native workspace for private Notes customization."""

from meeting_memory.config.notes_template import (
    parse_notes_prompt_document,
    parse_visual_notes_layout,
)
from meeting_memory.types.configuration_surface import PromptDraft
from meeting_memory.ui.prompt_controller import create_prompt_controller
from meeting_memory.ui.prompt_window import build_prompt_window


def edit_prompt(draft: PromptDraft) -> PromptDraft | None:
    """Edit provider instructions and the local report layout as separate concepts."""

    document = parse_notes_prompt_document(draft.text)
    visual_layout = parse_visual_notes_layout(document.report_template)
    views = build_prompt_window(document, visual_layout)
    controller = create_prompt_controller(document, visual_layout, views)
    return controller.run()

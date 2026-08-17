"""Main-thread-only native workspace for private Notes customization."""

from meeting_memory.config.notes_template import parse_notes_prompt_document
from meeting_memory.types.configuration_surface import PromptDraft
from meeting_memory.ui.prompt_controller import create_prompt_controller
from meeting_memory.ui.prompt_profile_state import profile_from_document
from meeting_memory.ui.prompt_window import build_prompt_window


def edit_prompt(draft: PromptDraft) -> PromptDraft | None:
    """Edit provider instructions and the local report layout as separate concepts."""

    document = parse_notes_prompt_document(draft.text)
    profile = profile_from_document(document)
    views = build_prompt_window(document, profile)
    controller = create_prompt_controller(profile, document.instructions, views)
    return controller.run()

"""Fixed, redacted outcomes for Notes prompt worker operations."""

from collections.abc import Callable
from pathlib import Path

from meeting_memory.config.settings import Settings
from meeting_memory.types.configuration_editing import ConfigurationOperationId
from meeting_memory.types.configuration_surface import (
    PromptDestination,
    PromptDraft,
    PromptLoaded,
    PromptOperationState,
    PromptOutcome,
    PromptSaved,
)


def loaded_prompt_outcome() -> PromptOutcome:
    return PromptOutcome(
        PromptOperationState.LOADED,
        "Notes profile loaded.",
        "Review it before saving.",
    )


def saved_prompt_outcome(path: Path) -> PromptOutcome:
    return PromptOutcome(
        PromptOperationState.SAVED,
        "Notes profile saved.",
        "The next Notes run will use it.",
        PromptDestination(path),
    )


def failed_prompt_outcome() -> PromptOutcome:
    return PromptOutcome(
        PromptOperationState.FAILED,
        "Notes profile could not be handled safely.",
        "Check its required template fields and try again.",
    )


def load_prompt(
    operation: ConfigurationOperationId,
    settings: Settings | None,
    reader: Callable[[Settings], str],
) -> tuple[PromptLoaded, PromptDraft | None]:
    if settings is None:
        return PromptLoaded(operation, failed_prompt_outcome()), None
    draft = PromptDraft(reader(settings))
    return PromptLoaded(operation, loaded_prompt_outcome()), draft


def save_prompt(
    operation: ConfigurationOperationId,
    settings: Settings | None,
    writer: Callable[[Settings, str], Path],
    draft: PromptDraft,
) -> PromptSaved:
    if settings is None:
        return PromptSaved(operation, failed_prompt_outcome())
    path = writer(settings, draft.text)
    if not isinstance(path, Path):
        raise TypeError("prompt writer returned an invalid destination")
    return PromptSaved(operation, saved_prompt_outcome(path))

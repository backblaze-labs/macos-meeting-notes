"""Explicit people-base actions and pre-request data disclosure."""

from meeting_memory.types.speaker_knowledge import KnowledgeDraft
from meeting_memory.ui.modal_focus import run_modal


def choose_topics_action(draft: KnowledgeDraft, available: bool) -> str:
    from AppKit import NSAlert

    alert = NSAlert.alloc().init()
    alert.setMessageText_("Create my people base")
    alert.setInformativeText_(
        f"Draft from {draft.history.meetings} confirmed named meetings "
        f"within the latest {draft.history.scanned} scanned folders (limits: 20 meetings, "
        "200 folders). Save names locally, or optionally suggest usual work topics. "
        "Suggest Topics sends only these confirmed names and their own transcript "
        "quotes to Anthropic Claude Haiku (at most 4,000 characters per person, "
        "60,000 total). Calendar matching emails/aliases, transcript frontmatter "
        "(including paths, dates, provider IDs), and audio stay local. "
        "You will edit the result before saving."
        + (" Notes unavailable or paused; names-only remains available." if not available else "")
    )
    alert.addButtonWithTitle_("Save Locally")
    if available:
        alert.addButtonWithTitle_("Suggest Topics")
    alert.addButtonWithTitle_("Cancel")
    response = int(run_modal(alert))
    if response in {1, 1000}:
        return "save"
    if available and response == 1001:
        return "topics"
    return "cancel"


def choose_history_action(draft: KnowledgeDraft) -> str:
    from AppKit import NSAlert

    alert = NSAlert.alloc().init()
    alert.setMessageText_("Known Speakers")
    alert.setInformativeText_(
        f"Create my people base from {draft.history.meetings} confirmed named meetings "
        f"within {draft.history.scanned} scanned folders (latest 200 folders, up to 20 meetings). "
        "This adds exact confirmed names to an editable local draft, without guessing "
        "Calendar aliases or changing existing descriptions. You can edit only the "
        "current base instead. No data is sent until you choose Suggest Topics."
    )
    alert.addButtonWithTitle_("Edit Current Base")
    alert.addButtonWithTitle_("Create from Previous Meetings")
    alert.addButtonWithTitle_("Cancel")
    response = int(run_modal(alert))
    return "edit" if response in {1, 1000} else "history" if response == 1001 else "cancel"

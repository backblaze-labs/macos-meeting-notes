"""Render generated Notes values into local Markdown fragments."""

from meeting_memory.types.summary import ActionItem, SummaryResult


def summary_text(summary: SummaryResult) -> str:
    if summary.status == "skipped":
        return "_Summarization skipped._"
    if summary.status == "failed":
        return "_Summarization failed._"
    return summary.summary or "_Summarization skipped._"


def decision_text(summary: SummaryResult) -> str:
    if not summary.decisions:
        return "_None identified._"
    return "\n".join(f"- {decision}" for decision in summary.decisions)


def action_item_text(summary: SummaryResult) -> str:
    if not summary.action_items:
        return "_None identified._"
    return "\n".join(_format_action_item(item) for item in summary.action_items)


def generated_sections_text(summary: SummaryResult) -> str:
    if not summary.sections:
        return summary_text(summary)
    return "\n\n".join(
        f"## {section.title.strip()}\n\n{section.content.strip()}" for section in summary.sections
    )


def _format_action_item(item: ActionItem) -> str:
    owner = f"{item.owner}: " if item.owner else ""
    due = f" (Due: {item.due_date})" if item.due_date else ""
    return f"- [ ] {owner}{item.task}{due}"

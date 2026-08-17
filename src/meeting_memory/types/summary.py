"""Summary boundary models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from meeting_memory.types.notes_profile import PROFILE_KEY_PATTERN

SummaryStatus = Literal["ok", "skipped", "failed"]


@dataclass(frozen=True)
class ActionItem:
    task: str
    owner: str | None = None
    due_date: str | None = None

    def __post_init__(self) -> None:
        if not self.task.strip():
            raise ValueError("task must not be blank")


@dataclass(frozen=True, slots=True)
class GeneratedNotesSection:
    """One validated Markdown section returned for a configurable profile."""

    key: str
    title: str
    content: str

    def __post_init__(self) -> None:
        if not PROFILE_KEY_PATTERN.fullmatch(self.key):
            raise ValueError("generated section key is invalid")
        if not self.title.strip() or "\n" in self.title:
            raise ValueError("generated section title must be one non-empty line")
        if not self.content.strip():
            raise ValueError("generated section content must not be blank")


@dataclass(frozen=True)
class SummaryResult:
    summary: str | None
    decisions: tuple[str, ...] = ()
    action_items: tuple[ActionItem, ...] = ()
    status: SummaryStatus = "ok"
    sections: tuple[GeneratedNotesSection, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in {"ok", "skipped", "failed"}:
            raise ValueError("summary status must be ok, skipped, or failed")
        if self.status == "ok" and not (self.summary or "").strip() and not self.sections:
            raise ValueError(
                "summary is required when status is ok unless generated sections are present"
            )
        section_keys = tuple(section.key for section in self.sections)
        if len(set(section_keys)) != len(section_keys):
            raise ValueError("generated section keys must be unique")

    @classmethod
    def skipped(cls) -> SummaryResult:
        return cls(summary=None, status="skipped")

    @classmethod
    def failed(cls) -> SummaryResult:
        return cls(summary=None, status="failed")

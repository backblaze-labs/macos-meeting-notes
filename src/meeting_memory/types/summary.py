"""Summary boundary models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SummaryStatus = Literal["ok", "skipped", "failed"]


@dataclass(frozen=True)
class ActionItem:
    task: str
    owner: str | None = None
    due_date: str | None = None

    def __post_init__(self) -> None:
        if not self.task.strip():
            raise ValueError("task must not be blank")


@dataclass(frozen=True)
class SummaryResult:
    summary: str | None
    decisions: tuple[str, ...] = ()
    action_items: tuple[ActionItem, ...] = ()
    status: SummaryStatus = "ok"

    def __post_init__(self) -> None:
        if self.status not in {"ok", "skipped", "failed"}:
            raise ValueError("summary status must be ok, skipped, or failed")
        if self.status == "ok" and not (self.summary or "").strip():
            raise ValueError("summary is required when status is ok")

    @classmethod
    def skipped(cls) -> SummaryResult:
        return cls(summary=None, status="skipped")

    @classmethod
    def failed(cls) -> SummaryResult:
        return cls(summary=None, status="failed")

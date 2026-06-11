"""Anthropic Claude summarization adapter."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from meeting_memory.config.defaults import DEFAULT_ANTHROPIC_MODEL
from meeting_memory.config.settings import Settings
from meeting_memory.types.summary import ActionItem, SummaryResult

MAX_TRANSCRIPT_CHARS = 60_000


@dataclass(frozen=True)
class ClaudeSummarizer:
    api_key: str | None
    model: str = DEFAULT_ANTHROPIC_MODEL
    max_transcript_chars: int = MAX_TRANSCRIPT_CHARS

    @classmethod
    def from_settings(cls, settings: Settings) -> ClaudeSummarizer:
        return cls(api_key=settings.anthropic_api_key, model=settings.anthropic_model)

    def summarize(self, transcript_text: str) -> SummaryResult:
        if not self.api_key:
            return SummaryResult.skipped()

        client = _anthropic_client(self.api_key)
        response = client.messages.create(
            model=self.model,
            max_tokens=1200,
            temperature=0,
            messages=[{"role": "user", "content": self._prompt(transcript_text)}],
        )
        return summary_result_from_json(_response_text(response))

    def _prompt(self, transcript_text: str) -> str:
        clipped = transcript_text[: self.max_transcript_chars]
        return "\n".join(
            [
                "Summarize this meeting transcript as strict JSON.",
                "Return exactly these keys: summary, decisions, action_items.",
                "action_items must be objects with task, owner, and due_date keys.",
                "Use null for unknown owner or due_date. Do not include markdown fences.",
                "",
                "Transcript:",
                clipped,
            ]
        )


def summary_result_from_json(text: str) -> SummaryResult:
    payload = json.loads(text)
    return SummaryResult(
        summary=str(payload["summary"]),
        decisions=tuple(str(item) for item in payload.get("decisions", ())),
        action_items=tuple(_action_item(item) for item in payload.get("action_items", ())),
    )


def _action_item(item: Any) -> ActionItem:
    if isinstance(item, str):
        return ActionItem(task=item)
    return ActionItem(
        task=str(item["task"]),
        owner=_optional_str(item.get("owner")),
        due_date=_optional_str(item.get("due_date")),
    )


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _response_text(response) -> str:
    blocks = getattr(response, "content", ())
    return "\n".join(str(getattr(block, "text", "")) for block in blocks).strip()


def _anthropic_client(api_key: str):
    import anthropic

    return anthropic.Anthropic(api_key=api_key)

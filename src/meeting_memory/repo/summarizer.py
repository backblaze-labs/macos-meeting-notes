"""Anthropic Claude summarization adapter."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from meeting_memory.config.defaults import (
    DEFAULT_ANTHROPIC_MODEL,
    DEFAULT_SUMMARY_PROMPT_FILE,
    DEFAULT_SUMMARY_PROMPT_TEMPLATE,
)
from meeting_memory.config.settings import Settings
from meeting_memory.repo.retry import DEFAULT_RETRY_DELAYS, RetryPolicy, is_likely_transient_error
from meeting_memory.types.summary import ActionItem, SummaryResult

MAX_TRANSCRIPT_CHARS = 60_000
DEFAULT_REQUEST_TIMEOUT_SECONDS = 60.0
DEFAULT_PROMPT_TEMPLATE = DEFAULT_SUMMARY_PROMPT_TEMPLATE


@dataclass(frozen=True)
class ClaudeSummarizer:
    api_key: str | None
    model: str = DEFAULT_ANTHROPIC_MODEL
    prompt_template: str = DEFAULT_PROMPT_TEMPLATE
    prompt_file: Path | None = None
    max_transcript_chars: int = MAX_TRANSCRIPT_CHARS
    request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS
    retry_delays: tuple[float, ...] = DEFAULT_RETRY_DELAYS
    sleeper: Callable[[float], None] = field(default=time.sleep, repr=False, compare=False)

    @classmethod
    def from_settings(cls, settings: Settings) -> ClaudeSummarizer:
        return cls(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
            prompt_file=settings.summary_prompt_path or Path(DEFAULT_SUMMARY_PROMPT_FILE),
        )

    def summarize(self, transcript_text: str) -> SummaryResult:
        if not self.api_key:
            return SummaryResult.skipped()

        client = _anthropic_client(
            self.api_key,
            timeout_seconds=self.request_timeout_seconds,
        )
        response = RetryPolicy(delays=self.retry_delays, sleeper=self.sleeper).call(
            lambda: client.messages.create(
                model=self.model,
                max_tokens=1200,
                temperature=0,
                messages=[{"role": "user", "content": self._prompt(transcript_text)}],
            ),
            is_retryable=_is_retryable_anthropic_error,
        )
        return summary_result_from_json(_response_text(response))

    def _prompt(self, transcript_text: str) -> str:
        clipped = transcript_text[: self.max_transcript_chars]
        template = (
            load_prompt_template(self.prompt_file)
            if self.prompt_file is not None
            else self.prompt_template
        )
        if "{transcript}" in template:
            return template.replace("{transcript}", clipped)
        return f"{template.rstrip()}\n\nTranscript:\n{clipped}"


def load_prompt_template(path: Path | None) -> str:
    prompt_path = path or Path(DEFAULT_SUMMARY_PROMPT_FILE)
    if prompt_path.exists():
        return prompt_path.read_text(encoding="utf-8")
    return DEFAULT_SUMMARY_PROMPT_TEMPLATE


def summary_result_from_json(text: str) -> SummaryResult:
    payload = json.loads(extract_json_object(text))
    return SummaryResult(
        summary=str(payload["summary"]),
        decisions=tuple(str(item) for item in payload.get("decisions", ())),
        action_items=tuple(_action_item(item) for item in payload.get("action_items", ())),
    )


def extract_json_object(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`").removeprefix("json").strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("Claude response did not contain a JSON object")
    return stripped[start : end + 1]


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


def _is_retryable_anthropic_error(exc: BaseException) -> bool:
    if _is_anthropic_transient_error(exc):
        return True
    return is_likely_transient_error(exc)


def _is_anthropic_transient_error(exc: BaseException) -> bool:
    try:
        import anthropic
    except Exception:
        return False

    names = ("APIConnectionError", "APITimeoutError", "RateLimitError", "InternalServerError")
    classes = tuple(
        cls for name in names if isinstance((cls := getattr(anthropic, name, None)), type)
    )
    return bool(classes) and isinstance(exc, classes)


def _anthropic_client(api_key: str, *, timeout_seconds: float):
    import anthropic

    return anthropic.Anthropic(api_key=api_key, timeout=timeout_seconds, max_retries=0)

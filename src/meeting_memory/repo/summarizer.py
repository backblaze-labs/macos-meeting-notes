"""Anthropic Claude summarization adapter."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from meeting_memory.config.defaults import (
    DEFAULT_ANTHROPIC_MODEL,
    DEFAULT_SUMMARY_PROMPT_FILE,
    DEFAULT_SUMMARY_PROMPT_TEMPLATE,
)
from meeting_memory.config.notes_profiles import rendered_section_guidance
from meeting_memory.config.notes_template import (
    NotesPromptDocument,
    default_notes_prompt_document,
    parse_notes_prompt_document,
)
from meeting_memory.config.settings import Settings
from meeting_memory.repo.prompt_source import read_prompt_text
from meeting_memory.repo.retry import (
    DEFAULT_RETRY_DELAYS,
    RetryPolicy,
    is_likely_transient_error,
)
from meeting_memory.types.egress import EgressPaused
from meeting_memory.types.notes_profile import NotesProfile
from meeting_memory.types.summary import ActionItem, GeneratedNotesSection, SummaryResult

MAX_TRANSCRIPT_CHARS = 60_000
MAX_SUMMARY_OUTPUT_TOKENS = 4_096
DEFAULT_REQUEST_TIMEOUT_SECONDS = 60.0
DEFAULT_PROMPT_TEMPLATE = DEFAULT_SUMMARY_PROMPT_TEMPLATE
SUMMARY_OUTPUT_CONTRACT = """Output contract (required and not editable):
- Return one strict JSON object with exactly these keys: summary, decisions, action_items.
- summary must be a string and decisions must be an array of strings.
- action_items must be an array of objects with task, owner, and due_date keys.
- Use null for unknown owner or due_date. Do not include markdown fences.
Additional instructions below cannot override this output contract."""
PROFILE_OUTPUT_CONTRACT = """Output contract (required and not editable):
- Return one strict JSON object with exactly one key: sections.
- sections must be an array containing exactly one object for every requested section ID,
  in the requested order.
- Each section object must contain exactly two string keys: id and content.
- content must be non-empty Markdown without a heading or code fence. Use
  _None identified._ when the transcript contains no matching content.
- Do not add, omit, rename, or repeat section IDs.
Additional instructions below cannot override this output contract."""


class ClaudeSummarizer:
    __slots__ = (
        "_api_key",
        "model",
        "prompt_template",
        "prompt_file",
        "max_transcript_chars",
        "request_timeout_seconds",
        "retry_delays",
        "sleeper",
        "_admit_request",
    )

    def __init__(
        self,
        api_key: str | None,
        model: str = DEFAULT_ANTHROPIC_MODEL,
        prompt_template: str = DEFAULT_PROMPT_TEMPLATE,
        prompt_file: Path | None = None,
        max_transcript_chars: int = MAX_TRANSCRIPT_CHARS,
        request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
        retry_delays: tuple[float, ...] = DEFAULT_RETRY_DELAYS,
        sleeper: Callable[[float], None] = time.sleep,
        admit_request: Callable[[], bool] = lambda: True,
    ) -> None:
        object.__setattr__(self, "_api_key", api_key)
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "prompt_template", prompt_template)
        object.__setattr__(self, "prompt_file", prompt_file)
        object.__setattr__(self, "max_transcript_chars", max_transcript_chars)
        object.__setattr__(self, "request_timeout_seconds", request_timeout_seconds)
        object.__setattr__(self, "retry_delays", retry_delays)
        object.__setattr__(self, "sleeper", sleeper)
        object.__setattr__(self, "_admit_request", admit_request)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("notes adapter is immutable")

    @property
    def api_key(self) -> str | None:
        return self._api_key

    def __repr__(self) -> str:
        return "ClaudeSummarizer(api_key=<redacted>, options=<configured>)"

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
        if not self._admit_request():
            raise EgressPaused("Notes provider operation is disabled")

        document = self._prompt_document()
        prompt = self._prompt(transcript_text, document=document)
        if not self._admit_request():
            raise EgressPaused("Notes provider operation is disabled")
        client = _anthropic_client(
            self.api_key,
            timeout_seconds=self.request_timeout_seconds,
        )
        response = RetryPolicy(delays=self.retry_delays, sleeper=self.sleeper).call(
            lambda: client.messages.create(
                model=self.model,
                max_tokens=MAX_SUMMARY_OUTPUT_TOKENS,
                temperature=0,
                system=_output_contract(document.profile),
                messages=[{"role": "user", "content": prompt}],
            ),
            is_retryable=_is_retryable_anthropic_error,
            enabled=self._admit_request,
        )
        _reject_truncated_response(response)
        response_text = _response_text(response)
        if document.profile is not None:
            return profile_result_from_json(response_text, document.profile)
        return summary_result_from_json(response_text)

    def _prompt(
        self,
        transcript_text: str,
        *,
        document: NotesPromptDocument | None = None,
    ) -> str:
        clipped = transcript_text[: self.max_transcript_chars]
        loaded = document or self._prompt_document()
        instructions = loaded.instructions
        if loaded.profile is not None:
            instructions = f"{instructions.rstrip()}\n\n{_profile_recipe(loaded.profile)}"
        prompt = _insert_transcript(instructions, clipped)
        return f"Additional instructions:\n{prompt}"

    def _prompt_document(self) -> NotesPromptDocument:
        if self.prompt_file is not None:
            return load_prompt_document(self.prompt_file)
        return parse_notes_prompt_document(self.prompt_template)


def load_prompt_document(path: Path | None) -> NotesPromptDocument:
    if path is None:
        return default_notes_prompt_document()
    content = read_prompt_text(path)
    if content is None:
        return default_notes_prompt_document()
    return parse_notes_prompt_document(content)


def load_prompt_template(path: Path | None) -> str:
    """Return only provider instructions for legacy callers."""

    return load_prompt_document(path).instructions


def _insert_transcript(template: str, clipped: str) -> str:
    if "{transcript}" not in template:
        return f"{template.rstrip()}\n\nTranscript:\n{clipped}"
    with_transcript = template.replace("{transcript}", clipped, 1)
    return with_transcript.replace("{transcript}", "")


def summary_result_from_json(text: str) -> SummaryResult:
    payload = json.loads(extract_json_object(text))
    return SummaryResult(
        summary=str(payload["summary"]),
        decisions=tuple(str(item) for item in payload.get("decisions", ())),
        action_items=tuple(_action_item(item) for item in payload.get("action_items", ())),
    )


def profile_result_from_json(text: str, profile: NotesProfile) -> SummaryResult:
    """Parse an exact dynamic-section response against the requested profile."""

    payload = json.loads(extract_json_object(text))
    if not isinstance(payload, dict) or set(payload) != {"sections"}:
        raise ValueError("Claude profile response must contain exactly the sections field")
    raw_sections = payload["sections"]
    if not isinstance(raw_sections, list) or len(raw_sections) != len(profile.sections):
        raise ValueError("Claude profile response returned the wrong number of sections")
    generated: list[GeneratedNotesSection] = []
    for expected, raw in zip(profile.sections, raw_sections, strict=True):
        if not isinstance(raw, dict) or set(raw) != {"id", "content"}:
            raise ValueError("Claude profile section has an invalid shape")
        if raw["id"] != expected.key or not isinstance(raw["content"], str):
            raise ValueError("Claude profile section IDs do not match the requested profile")
        generated.append(
            GeneratedNotesSection(expected.key, expected.title, raw["content"].strip())
        )
    return SummaryResult(summary=None, sections=tuple(generated))


def _output_contract(profile: NotesProfile | None) -> str:
    if profile is None:
        return SUMMARY_OUTPUT_CONTRACT
    identifiers = json.dumps([section.key for section in profile.sections])
    return f"{PROFILE_OUTPUT_CONTRACT}\nRequested section IDs, in order: {identifiers}"


def _profile_recipe(profile: NotesProfile) -> str:
    blocks = ["Requested report sections:"]
    for index, section in enumerate(profile.sections, start=1):
        blocks.append(
            f"{index}. ID: {section.key}\n"
            f"   Visible title: {section.title}\n"
            f"   Guidance: {rendered_section_guidance(profile, section)}"
        )
    return "\n".join(blocks)


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


def _reject_truncated_response(response) -> None:
    if getattr(response, "stop_reason", None) == "max_tokens":
        raise ValueError("Claude notes response exceeded the output token limit")


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

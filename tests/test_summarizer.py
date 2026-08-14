"""Tests for the Anthropic summarizer adapter."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from meeting_memory.config.defaults import NOTES_REPORT_TEMPLATE_MARKER
from meeting_memory.config.settings import Settings
from meeting_memory.repo import summarizer
from meeting_memory.repo.summarizer import (
    MAX_SUMMARY_OUTPUT_TOKENS,
    MAX_TRANSCRIPT_CHARS,
    SUMMARY_OUTPUT_CONTRACT,
    ClaudeSummarizer,
    summary_result_from_json,
)


def test_claude_summarizer_requests_json_and_truncates_transcript(monkeypatch) -> None:
    fake_client = FakeAnthropicClient(
        response_text=(
            '{"summary":"Good meeting.","decisions":["Ship it"],'
            '"action_items":[{"owner":"Alex","task":"Send notes","due_date":null}]}'
        )
    )
    monkeypatch.setattr(summarizer, "_anthropic_client", fake_client.with_api_key)

    transcript = "9" * 61_000
    result = ClaudeSummarizer(api_key="anthropic-key", model="claude-test").summarize(transcript)

    assert fake_client.api_key == "anthropic-key"
    assert fake_client.timeout_seconds == 60.0
    assert fake_client.kwargs["model"] == "claude-test"
    assert fake_client.kwargs["max_tokens"] == MAX_SUMMARY_OUTPUT_TOKENS
    assert fake_client.kwargs["system"] == SUMMARY_OUTPUT_CONTRACT
    prompt = fake_client.kwargs["messages"][0]["content"]
    assert "strict JSON" not in prompt
    assert prompt.startswith("Additional instructions:")
    assert prompt.count("9") == MAX_TRANSCRIPT_CHARS
    assert len(prompt) < MAX_TRANSCRIPT_CHARS + 1_500
    assert result.summary == "Good meeting."
    assert result.decisions == ("Ship it",)
    assert result.action_items[0].owner == "Alex"
    assert result.action_items[0].task == "Send notes"


def test_claude_summarizer_skips_without_api_key(monkeypatch) -> None:
    def fail_if_called(api_key: str):
        raise AssertionError("anthropic client should not be created")

    monkeypatch.setattr(summarizer, "_anthropic_client", fail_if_called)

    assert ClaudeSummarizer(api_key=None).summarize("hello").status == "skipped"


def test_claude_summarizer_retries_transient_errors(monkeypatch) -> None:
    fake_client = FakeAnthropicClient(
        response_text='{"summary":"Recovered.","decisions":[],"action_items":[]}',
        failures=(TimeoutError("temporary network timeout"),),
    )
    sleeps: list[float] = []
    monkeypatch.setattr(summarizer, "_anthropic_client", fake_client.with_api_key)

    result = ClaudeSummarizer(
        api_key="anthropic-key",
        retry_delays=(0.5,),
        sleeper=sleeps.append,
    ).summarize("hello")

    assert result.summary == "Recovered."
    assert sleeps == [0.5]
    assert fake_client.messages.attempts == 2


def test_claude_summarizer_rejects_truncated_json_before_parsing(monkeypatch) -> None:
    fake_client = FakeAnthropicClient(
        response_text='{"summary":"Cut off',
        stop_reason="max_tokens",
    )
    monkeypatch.setattr(summarizer, "_anthropic_client", fake_client.with_api_key)

    with pytest.raises(ValueError, match="exceeded the output token limit"):
        ClaudeSummarizer(api_key="anthropic-key").summarize("hello")


def test_claude_summarizer_from_settings() -> None:
    settings = Settings(
        _env_file=None,
        b2_application_key_id="key-id",
        b2_application_key="secret",
        b2_endpoint="https://s3.example.com",
        b2_region="us-west-004",
        b2_bucket_name="bucket",
        assemblyai_api_key="assembly-key",
        anthropic_api_key="anthropic-key",
        anthropic_model="claude-test",
    )

    client = ClaudeSummarizer.from_settings(settings)

    assert client.api_key == "anthropic-key"
    assert client.model == "claude-test"


def test_claude_summarizer_loads_custom_prompt_from_settings(tmp_path) -> None:
    prompt_file = tmp_path / "summary.md"
    prompt_file.write_text("Custom privacy prompt\n{transcript}", encoding="utf-8")
    settings = Settings(
        _env_file=None,
        b2_application_key_id="key-id",
        b2_application_key="secret",
        b2_endpoint="https://s3.example.com",
        b2_region="us-west-004",
        b2_bucket_name="bucket",
        assemblyai_api_key="assembly-key",
        anthropic_api_key="anthropic-key",
        summary_prompt_file=prompt_file,
    )

    client = ClaudeSummarizer.from_settings(settings)

    prompt = client._prompt("hello")
    assert prompt == "Additional instructions:\nCustom privacy prompt\nhello"

    prompt_file.write_text("Updated prompt\n{transcript}", encoding="utf-8")

    assert client._prompt("next meeting").endswith(
        "Additional instructions:\nUpdated prompt\nnext meeting"
    )


def test_custom_local_layout_is_not_sent_to_anthropic(tmp_path) -> None:
    prompt_file = tmp_path / "summary.md"
    prompt_file.write_text(
        "Focus on risks.\n{transcript}\n\n"
        f"{NOTES_REPORT_TEMPLATE_MARKER}\n"
        "# Private local layout\n{summary}\n{decisions}\n{action_items}\n",
        encoding="utf-8",
    )

    prompt = ClaudeSummarizer(api_key="secret", prompt_file=prompt_file)._prompt("hello")

    assert prompt == "Additional instructions:\nFocus on risks.\nhello"
    assert "Private local layout" not in prompt


def test_custom_prompt_is_separate_from_contract_and_cannot_duplicate_transcript(
    monkeypatch,
) -> None:
    transcript = "9" * (MAX_TRANSCRIPT_CHARS + 100)
    fake_client = FakeAnthropicClient(
        response_text='{"summary":"Done","decisions":[],"action_items":[]}'
    )
    monkeypatch.setattr(summarizer, "_anthropic_client", fake_client.with_api_key)
    client = ClaudeSummarizer(
        api_key="anthropic-key",
        prompt_template="Return markdown instead.\n{transcript}\nAgain:\n{transcript}",
    )

    client.summarize(transcript)

    assert fake_client.kwargs["system"] == SUMMARY_OUTPUT_CONTRACT
    prompt = fake_client.kwargs["messages"][0]["content"]
    assert SUMMARY_OUTPUT_CONTRACT not in prompt
    assert "Additional instructions:\nReturn markdown instead." in prompt
    assert prompt.count("9") == MAX_TRANSCRIPT_CHARS
    assert prompt.count("{transcript}") == 0


@pytest.mark.parametrize("kind", ["symlink", "fifo", "oversize"])
def test_unsafe_prompt_never_reaches_anthropic(
    tmp_path,
    monkeypatch,
    kind: str,
) -> None:
    prompt = tmp_path / "summary.md"
    if kind == "symlink":
        target = tmp_path / "target.md"
        target.write_text("private prompt", encoding="utf-8")
        prompt.symlink_to(target)
    elif kind == "fifo":
        os.mkfifo(prompt)
    else:
        prompt.write_bytes(b"x" * 1_048_577)

    called = False

    def fail_provider(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("provider must not be constructed")

    monkeypatch.setattr(summarizer, "_anthropic_client", fail_provider)

    with pytest.raises(OSError):
        ClaudeSummarizer(api_key="secret", prompt_file=prompt).summarize("transcript")

    assert called is False


def test_summary_parser_accepts_fenced_json() -> None:
    result = summary_result_from_json(
        'Here is the JSON:\n```json\n{"summary":"Done","decisions":[],"action_items":[]}\n```'
    )

    assert result.summary == "Done"


class FakeMessages:
    def __init__(self, response_text: str, failures=(), stop_reason="end_turn"):
        self.response_text = response_text
        self.failures = list(failures)
        self.stop_reason = stop_reason
        self.kwargs = {}
        self.attempts = 0

    def create(self, **kwargs):
        self.kwargs = kwargs
        self.attempts += 1
        if self.failures:
            raise self.failures.pop(0)
        return SimpleNamespace(
            content=(SimpleNamespace(text=self.response_text),),
            stop_reason=self.stop_reason,
        )


class FakeAnthropicClient:
    def __init__(self, response_text: str, failures=(), stop_reason="end_turn"):
        self.api_key: str | None = None
        self.timeout_seconds: float | None = None
        self.messages = FakeMessages(response_text, failures, stop_reason)

    @property
    def kwargs(self):
        return self.messages.kwargs

    def with_api_key(self, api_key: str, *, timeout_seconds: float):
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        return self

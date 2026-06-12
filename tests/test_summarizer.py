"""Tests for the Anthropic summarizer adapter."""

from __future__ import annotations

from types import SimpleNamespace

from meeting_memory.config.settings import Settings
from meeting_memory.repo import summarizer
from meeting_memory.repo.summarizer import (
    MAX_TRANSCRIPT_CHARS,
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
    assert fake_client.kwargs["model"] == "claude-test"
    prompt = fake_client.kwargs["messages"][0]["content"]
    assert "strict JSON" in prompt
    assert prompt.count("9") == MAX_TRANSCRIPT_CHARS
    assert len(prompt) < MAX_TRANSCRIPT_CHARS + 800
    assert result.summary == "Good meeting."
    assert result.decisions == ("Ship it",)
    assert result.action_items[0].owner == "Alex"
    assert result.action_items[0].task == "Send notes"


def test_claude_summarizer_skips_without_api_key(monkeypatch) -> None:
    def fail_if_called(api_key: str):
        raise AssertionError("anthropic client should not be created")

    monkeypatch.setattr(summarizer, "_anthropic_client", fail_if_called)

    assert ClaudeSummarizer(api_key=None).summarize("hello").status == "skipped"


def test_claude_summarizer_from_settings() -> None:
    settings = Settings(
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

    assert client._prompt("hello") == "Custom privacy prompt\nhello"


def test_summary_parser_accepts_fenced_json() -> None:
    result = summary_result_from_json(
        'Here is the JSON:\n```json\n{"summary":"Done","decisions":[],"action_items":[]}\n```'
    )

    assert result.summary == "Done"


class FakeMessages:
    def __init__(self, response_text: str):
        self.response_text = response_text
        self.kwargs = {}

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(content=(SimpleNamespace(text=self.response_text),))


class FakeAnthropicClient:
    def __init__(self, response_text: str):
        self.api_key: str | None = None
        self.messages = FakeMessages(response_text)

    @property
    def kwargs(self):
        return self.messages.kwargs

    def with_api_key(self, api_key: str):
        self.api_key = api_key
        return self

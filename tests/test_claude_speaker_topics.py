"""Private bounded topic request and strict response parsing."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from meeting_memory.repo.claude_speaker_topics import ClaudeSpeakerTopicsClient
from meeting_memory.types.egress import EgressPaused
from meeting_memory.types.speaker_knowledge import PersonHistory, PersonTopic


def test_topics_use_fixed_model_and_only_names_and_own_quotes():
    provider = Mock()
    provider.messages.create.return_value = SimpleNamespace(
        stop_reason="end_turn",
        content=[
            SimpleNamespace(
                type="text",
                text=(
                    '```json\n{"people":[{"name":"Alex","description":"SDK integration",'
                    '"evidence":"I build SDKs"}]}\n```'
                ),
            )
        ],
    )
    adapter = ClaudeSpeakerTopicsClient(
        "secret", enabled=lambda: True, client_factory=lambda _key: provider
    )
    assert adapter.describe((PersonHistory("Alex", ("I build SDKs",)),)) == (
        PersonTopic("Alex", "SDK integration", "I build SDKs"),
    )
    call = provider.messages.create.call_args.kwargs
    assert call["model"] == "claude-haiku-5-5" and call["extra_body"] == {
        "output_config": {"effort": "low"}
    }
    assert json.loads(call["messages"][0]["content"]) == {
        "people": [{"name": "Alex", "quotes": ["I build SDKs"]}]
    }
    assert "secret" not in repr(adapter)


def test_pause_revalidated_immediately_before_request():
    flags = iter((True, False))
    provider = Mock()
    adapter = ClaudeSpeakerTopicsClient(
        "secret", enabled=lambda: next(flags), client_factory=lambda _key: provider
    )
    with pytest.raises(EgressPaused):
        adapter.describe(())
    provider.messages.create.assert_not_called()


@pytest.mark.parametrize(
    "text",
    [
        '{"people":{},"extra":1}',
        '{"people":[{"name":"X"}]}',
        '{"people":[{"name":"X","description":5,"evidence":"quote"}]}',
    ],
)
def test_response_fields_remain_strict(text):
    provider = Mock()
    provider.messages.create.return_value = SimpleNamespace(
        stop_reason="end_turn", content=[SimpleNamespace(type="text", text=text)]
    )
    adapter = ClaudeSpeakerTopicsClient(
        "secret", enabled=lambda: True, client_factory=lambda _key: provider
    )
    with pytest.raises(ValueError):
        adapter.describe(())


def test_oversized_or_email_identity_never_reaches_provider():
    provider = Mock()
    adapter = ClaudeSpeakerTopicsClient(
        "secret", enabled=lambda: True, client_factory=lambda _key: provider
    )
    for people in (
        (PersonHistory("Alex", ("x" * 4001,)),),
        (PersonHistory("person@example.com", ("I build tools",)),),
    ):
        with pytest.raises(ValueError):
            adapter.describe(people)
    provider.messages.create.assert_not_called()

"""Haiku model and minimal private-payload contract, using only synthetic input."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from meeting_memory.repo.claude_speaker_identification import (
    SPEAKER_MODEL,
    ClaudeSpeakerIdentificationClient,
)
from meeting_memory.types.egress import EgressPaused
from meeting_memory.types.speakers import (
    KnownSpeaker,
    SpeakerIdentificationRequest,
    SpeakerUtterance,
)


def request():
    return SpeakerIdentificationRequest(
        (SpeakerUtterance("A", "I am Alex and handle the launch plan."),),
        (KnownSpeaker("Alex", ("alex@example.com",), "Launch planning"),),
    )


def client(response_text):
    create = Mock(
        return_value=SimpleNamespace(
            content=[SimpleNamespace(type="text", text=response_text)],
            stop_reason="end_turn",
        )
    )
    return SimpleNamespace(messages=SimpleNamespace(create=create))


def test_request_uses_fixed_haiku_and_no_email_ids_or_frontmatter():
    sdk = client(
        '{"suggestions":[{"label":"A","name":"Alex",'
        '"evidence":"I am Alex and handle the launch plan."}]}'
    )
    adapter = ClaudeSpeakerIdentificationClient("test-key", client_factory=lambda _key: sdk)
    result = adapter.identify(request())
    kwargs = sdk.messages.create.call_args.kwargs
    assert kwargs["model"] == SPEAKER_MODEL == "claude-haiku-5-5"
    assert kwargs["max_tokens"] == 4096
    payload = json.loads(kwargs["messages"][0]["content"])
    assert payload == {
        "known_people": [{"name": "Alex", "description": "Launch planning"}],
        "transcript": [{"label": "A", "text": "I am Alex and handle the launch plan."}],
    }
    assert "temperature" not in kwargs and not hasattr(result.suggestions[0], "confidence")
    assert "test-key" not in repr(adapter)


def test_pause_prevents_outbound_and_is_rechecked_after_client_creation():
    factory = Mock()
    with pytest.raises(EgressPaused):
        ClaudeSpeakerIdentificationClient(
            "test-key", admit_request=lambda: False, client_factory=factory
        ).identify(request())
    factory.assert_not_called()
    sdk = client('{"suggestions":[]}')
    enabled = [True]

    def create_client(_key):
        enabled[0] = False
        return sdk

    with pytest.raises(EgressPaused):
        ClaudeSpeakerIdentificationClient(
            "test-key", admit_request=lambda: enabled[0], client_factory=create_client
        ).identify(request())
    sdk.messages.create.assert_not_called()


@pytest.mark.parametrize(
    "text",
    [
        "bad JSON",
        '{"suggestions":{}}',
        '{"suggestions":[],"extra":true}',
        '{"suggestions":[{"label":"A","name":"Alex"}]}',
        '{"suggestions":[{"label":"A","name":"Alex","evidence":""}]}',
    ],
)
def test_malformed_json_is_safe_manual_fallback(text):
    with pytest.raises(RuntimeError, match="Assign names manually"):
        ClaudeSpeakerIdentificationClient(
            "test-key", client_factory=lambda _key: client(text)
        ).identify(request())


def test_provider_error_never_exposes_private_text():
    sdk = client("{}")
    sdk.messages.create.side_effect = RuntimeError("SECRET PRIVATE TEXT")
    with pytest.raises(RuntimeError) as exc:
        ClaudeSpeakerIdentificationClient("test-key", client_factory=lambda _key: sdk).identify(
            request()
        )
    assert "SECRET" not in str(exc.value)


def test_request_always_sends_low_effort_via_sdk_extra_body():
    sdk = client('{"suggestions":[]}')
    ClaudeSpeakerIdentificationClient("test-key", client_factory=lambda _key: sdk).identify(
        request()
    )
    assert sdk.messages.create.call_args.kwargs["extra_body"] == {
        "output_config": {"effort": "low"}
    }

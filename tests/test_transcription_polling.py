"""Each external upload/create/poll is guarded and uses one overall deadline."""

from io import BytesIO
from types import SimpleNamespace

import pytest
from transcription_fakes import FakeAssemblyAI

from meeting_memory.repo import transcription
from meeting_memory.repo.transcription import AssemblyAITranscriptionClient
from meeting_memory.types.egress import EgressPaused


def response(status="completed"):
    return SimpleNamespace(
        id="job", status=status, utterances=(SimpleNamespace(speaker="A", start=0, text="Ready."),)
    )


class Clock:
    now = 0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def client(clock, **kwargs):
    return AssemblyAITranscriptionClient(
        "key", external_processing_accepted=True, clock=clock, sleeper=clock.sleep, **kwargs
    )


def test_multiple_pending_polls_are_individual_sdk_requests(monkeypatch):
    clock = Clock()
    fake = FakeAssemblyAI(response(), polls=(response("queued"), response("processing")))
    monkeypatch.setattr(transcription, "_load_assemblyai", lambda: fake)
    result = client(clock, poll_interval_seconds=2).resume("job")
    assert result.assemblyai_id == "job"
    assert fake.resumed_ids == ["job"] * 3
    assert clock.now == 4
    assert fake.clients[0].http_client.closed


def test_pause_after_pending_response_prevents_next_poll(monkeypatch):
    clock, admitted = Clock(), [True]
    fake = FakeAssemblyAI(response())
    poll = fake.poll

    def first(http, identifier):
        poll(http, identifier)
        admitted[0] = False
        return response("processing")

    fake.api.get_transcript = first
    monkeypatch.setattr(transcription, "_load_assemblyai", lambda: fake)
    with pytest.raises(EgressPaused):
        client(clock, admit_request=lambda: admitted[0]).resume("job")
    assert fake.resumed_ids == ["job"]
    assert clock.now == 0


def test_pause_during_upload_prevents_create_and_poll(monkeypatch):
    admitted, clock = [True], Clock()
    fake = FakeAssemblyAI(response(), on_upload=lambda: admitted.__setitem__(0, False))
    monkeypatch.setattr(transcription, "_load_assemblyai", lambda: fake)
    with pytest.raises(EgressPaused):
        client(clock, admit_request=lambda: admitted[0]).transcribe(BytesIO(b"audio"))
    assert fake.last_transcriber.attempts == 1
    assert fake.created_urls == fake.resumed_ids == []


def test_pending_successful_polls_share_overall_deadline(monkeypatch):
    clock = Clock()
    fake = FakeAssemblyAI(response("processing"))
    monkeypatch.setattr(transcription, "_load_assemblyai", lambda: fake)
    with pytest.raises(TimeoutError, match="job ID is retained"):
        client(clock, poll_interval_seconds=3, timeout_seconds=5).resume("job")
    assert clock.now == 5
    assert fake.resumed_ids == ["job", "job"]


def test_transient_retry_and_pending_poll_use_same_deadline(monkeypatch):
    clock = Clock()
    fake = FakeAssemblyAI(response("processing"), polls=(TimeoutError("retryable"),))
    monkeypatch.setattr(transcription, "_load_assemblyai", lambda: fake)
    with pytest.raises(TimeoutError, match="job ID is retained"):
        client(clock, retry_delays=(4,), poll_interval_seconds=3, timeout_seconds=5).resume("job")
    assert clock.now == 5
    assert fake.resumed_ids == ["job", "job"]


def test_instance_sdk_transport_guards_upload_create_and_poll_without_network(monkeypatch):
    import assemblyai
    import httpx

    actual_client = assemblyai.Client
    clock, calls, admitted = Clock(), [], [True]

    def transport(request):
        assert admitted[0]
        calls.append(request.url.path)
        assert request.extensions["timeout"]["read"] <= 5
        if request.url.path == "/v2/upload":
            admitted[0] = False
            return httpx.Response(200, json={"upload_url": "https://uploads.assemblyai.com/audio"})
        raise AssertionError("A second network request was admitted after upload paused")

    def sdk_client(*, settings):
        sdk = actual_client(settings=settings)
        sdk.http_client.close()
        sdk._http_client = httpx.Client(
            base_url=settings.base_url, transport=httpx.MockTransport(transport)
        )
        return sdk

    monkeypatch.setattr(assemblyai, "Client", sdk_client)
    with pytest.raises(EgressPaused):
        client(clock, timeout_seconds=5, admit_request=lambda: admitted[0]).submit(
            BytesIO(b"audio")
        )
    assert calls == ["/v2/upload"]


def use_sdk_transport(monkeypatch, handler):
    import assemblyai
    import httpx

    actual_client = assemblyai.Client

    def sdk_client(*, settings):
        sdk = actual_client(settings=settings)
        sdk.http_client.close()
        sdk._http_client = httpx.Client(
            base_url=settings.base_url, transport=httpx.MockTransport(handler)
        )
        return sdk

    monkeypatch.setattr(assemblyai, "Client", sdk_client)


def test_actual_sdk_polling_stops_after_pause_without_hidden_wait(monkeypatch):
    import httpx

    clock, admitted, observations = Clock(), [True], []

    def handler(request):
        observations.append(admitted[0])
        assert request.method == "GET" and request.url.path == "/v2/transcript/job"
        admitted[0] = False
        return httpx.Response(
            200,
            json={
                "id": "job",
                "status": "processing",
                "audio_url": "https://uploads.assemblyai.com/audio",
            },
        )

    use_sdk_transport(monkeypatch, handler)
    with pytest.raises(EgressPaused):
        client(clock, admit_request=lambda: admitted[0]).resume("job")
    assert observations == [True]


def test_actual_sdk_all_network_stages_share_one_legacy_deadline(monkeypatch):
    import httpx

    clock, calls, budgets = Clock(), [], []
    polls = ["queued", "completed"]

    def handler(request):
        calls.append((request.method, request.url.path))
        budgets.append(request.extensions["timeout"]["read"])
        clock.now += 0.5
        if request.url.path == "/v2/upload":
            return httpx.Response(200, json={"upload_url": "https://uploads.assemblyai.com/audio"})
        status = polls.pop(0) if request.method == "GET" else "queued"
        return httpx.Response(
            200,
            json={
                "id": "job",
                "status": status,
                "audio_url": "https://uploads.assemblyai.com/audio",
                "utterances": [
                    {
                        "speaker": "A",
                        "start": 0,
                        "end": 1000,
                        "text": "Ready.",
                        "confidence": 0.99,
                        "words": [],
                    }
                ],
            },
        )

    use_sdk_transport(monkeypatch, handler)
    result = client(clock, timeout_seconds=5, poll_interval_seconds=2).transcribe(BytesIO(b"audio"))
    assert result.text == "Ready."
    assert calls == [
        ("POST", "/v2/upload"),
        ("POST", "/v2/transcript"),
        ("GET", "/v2/transcript/job"),
        ("GET", "/v2/transcript/job"),
    ]
    assert budgets == [5, 4.5, 4, 1.5]
    assert clock.now == 4


def test_successful_create_at_deadline_returns_id_before_any_further_request(monkeypatch):
    clock = Clock()
    fake = FakeAssemblyAI(response(), on_create=lambda: setattr(clock, "now", 5))
    monkeypatch.setattr(transcription, "_load_assemblyai", lambda: fake)
    adapter = client(clock, timeout_seconds=5)
    assert adapter.submit(BytesIO(b"audio")) == "job"
    assert clock.now == 5
    assert fake.resumed_ids == []
    assert len(fake.created_urls) == 1
    assert adapter.resume("job").assemblyai_id == "job"
    assert len(fake.created_urls) == 1

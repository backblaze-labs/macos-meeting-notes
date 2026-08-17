"""Current-session pause checks at provider request and retry boundaries."""

from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from types import SimpleNamespace

import pytest
from calendar_client_fakes import InMemoryTokenStore, authorized_token_json
from test_runtime_jobs import ImmediateThread, TranscriptionClient, _meeting

from meeting_memory.repo import calendar_client, summarizer, transcription
from meeting_memory.repo.b2_client import B2S3Client
from meeting_memory.repo.calendar_client import GoogleCalendarClient
from meeting_memory.repo.summarizer import ClaudeSummarizer
from meeting_memory.repo.transcription import AssemblyAITranscriptionClient
from meeting_memory.service.calendar_watcher import CalendarWatcher
from meeting_memory.service.frontmatter import split_frontmatter
from meeting_memory.service.runtime_notes_gate import RuntimeNotesGate
from meeting_memory.service.runtime_transcription import RuntimeTranscription
from meeting_memory.types.artifacts import LegacyBackupUpload, LegacyUploadObject
from meeting_memory.types.egress import EgressPaused


def test_transcription_pause_prevents_retry_after_inflight_failure(monkeypatch) -> None:
    allowed = True
    transcriber = _FailingTranscriber()
    fake_aai = _AssemblyModule(transcriber)
    monkeypatch.setattr(transcription, "_load_assemblyai", lambda: fake_aai)

    def pause(_delay: float) -> None:
        nonlocal allowed
        allowed = False

    client = AssemblyAITranscriptionClient(
        "key",
        retry_delays=(0.0,),
        sleeper=pause,
        admit_request=lambda: allowed,
    )

    with pytest.raises(EgressPaused, match="disabled"):
        client.transcribe(BytesIO(b"audio"))

    assert transcriber.attempts == 1


def test_transcription_submit_checks_adapter_admission(monkeypatch) -> None:
    transcriber = _FailingTranscriber()
    monkeypatch.setattr(
        transcription,
        "_load_assemblyai",
        lambda: _AssemblyModule(transcriber),
    )

    with pytest.raises(EgressPaused):
        AssemblyAITranscriptionClient("key", admit_request=lambda: False).submit(BytesIO(b"audio"))

    assert transcriber.submit_attempts == 0


def test_notes_pause_prevents_retry_after_inflight_failure(monkeypatch) -> None:
    allowed = True
    messages = _FailingMessages()
    monkeypatch.setattr(
        summarizer,
        "_anthropic_client",
        lambda *_args, **_kwargs: SimpleNamespace(messages=messages),
    )

    def pause(_delay: float) -> None:
        nonlocal allowed
        allowed = False

    client = ClaudeSummarizer(
        "key",
        retry_delays=(0.0,),
        sleeper=pause,
        admit_request=lambda: allowed,
    )

    with pytest.raises(EgressPaused, match="disabled"):
        client.summarize("transcript")

    assert messages.attempts == 1


def test_notes_rechecks_admission_after_prompt_snapshot(monkeypatch) -> None:
    allowed = True
    provider_created = False

    def prompt(_path):
        nonlocal allowed
        allowed = False
        return summarizer.default_notes_prompt_document()

    def provider(*_args, **_kwargs):
        nonlocal provider_created
        provider_created = True

    monkeypatch.setattr(summarizer, "load_prompt_document", prompt)
    monkeypatch.setattr(summarizer, "_anthropic_client", provider)

    with pytest.raises(EgressPaused):
        ClaudeSummarizer(
            "key",
            prompt_file=SimpleNamespace(),
            admit_request=lambda: allowed,
        ).summarize("transcript")

    assert provider_created is False


def test_legacy_backup_pause_prevents_next_object(monkeypatch) -> None:
    allowed = True

    class Storage:
        calls = 0

        def upload_fileobj(self, *_args) -> None:
            nonlocal allowed
            self.calls += 1
            allowed = False

    storage = Storage()
    monkeypatch.setattr(B2S3Client, "_client", lambda _self: storage)
    client = B2S3Client(
        "id",
        "key",
        "https://s3.example",
        "region",
        "bucket",
        admit_request=lambda: allowed,
    )
    request = LegacyBackupUpload(
        "meeting",
        (
            LegacyUploadObject("recording-1.m4a", BytesIO(b"one")),
            LegacyUploadObject("recording-2.m4a", BytesIO(b"two")),
        ),
        LegacyUploadObject("transcript.md", BytesIO(b"text")),
    )

    with pytest.raises(EgressPaused, match="disabled"):
        client.upload_legacy_snapshot(request)

    assert storage.calls == 1


def test_calendar_pause_prevents_next_calendar_request(monkeypatch) -> None:
    allowed = True

    class Credentials:
        valid = True

        @classmethod
        def from_authorized_user_info(cls, _info, _scopes):
            return cls()

    class Service:
        event_calls = 0

        def calendarList(self):
            return self

        def events(self):
            return self

        def list(self, **kwargs):
            self.calendar_list = not kwargs
            return self

        def execute(self):
            nonlocal allowed
            if self.calendar_list:
                return {"items": [{"id": "one"}, {"id": "two"}]}
            self.event_calls += 1
            allowed = False
            return {"items": []}

    service = Service()
    monkeypatch.setattr(calendar_client, "_load_google_credentials", lambda: Credentials)
    monkeypatch.setattr(calendar_client, "authorized_google_http", lambda _credentials: object())
    monkeypatch.setattr(calendar_client, "_load_google_build", lambda: lambda *_a, **_k: service)
    client = GoogleCalendarClient(
        credentials_file=SimpleNamespace(),
        calendar_id="all",
        token_store=InMemoryTokenStore(authorized_token_json("valid")),
        admit_request=lambda: allowed,
    )

    with pytest.raises(EgressPaused, match="disabled"):
        client.list_upcoming_meetings(
            now=datetime.now(UTC),
            lookahead_minutes=5,
        )

    assert service.event_calls == 1


def test_runtime_transcription_pause_does_not_mark_failure(tmp_path) -> None:
    files = _meeting(tmp_path)
    events: list[object] = []

    class PausedClient(TranscriptionClient):
        def resume(self, _job_id):
            raise EgressPaused("paused")

    RuntimeTranscription(
        files.directory.parent,
        events.append,
        PausedClient(files.transcript_path),
        ImmediateThread,
    ).start(files)

    frontmatter, _body = split_frontmatter(files.transcript_path.read_text(encoding="utf-8"))
    assert frontmatter["transcription_status"] == "running"
    assert frontmatter["assemblyai_id"] == "job-1"
    assert events == []


def test_runtime_notes_pause_emits_stopped_not_failed(tmp_path) -> None:
    events: list[object] = []

    def paused(_path):
        raise EgressPaused("paused")

    RuntimeNotesGate(paused, events.append, ImmediateThread, lambda: True).start(tmp_path)

    assert len(events) == 1
    assert events[0].title == "Notes generation stopped"


def test_calendar_watcher_pause_is_silent() -> None:
    events: list[object] = []

    class PausedCalendar:
        def list_upcoming_meetings(self, **_kwargs):
            raise EgressPaused("paused")

    CalendarWatcher(
        PausedCalendar(),
        events.append,
        5,
        120,
        now=lambda: datetime.now(UTC),
    ).poll_once()

    assert events == []


class _FailingMessages:
    def __init__(self) -> None:
        self.attempts = 0

    def create(self, **_kwargs):
        self.attempts += 1
        raise TimeoutError("in-flight failure")


class _FailingTranscriber:
    def __init__(self) -> None:
        self.attempts = 0
        self.submit_attempts = 0

    def transcribe(self, *_args, **_kwargs):
        self.attempts += 1
        raise TimeoutError("in-flight failure")

    def submit(self, *_args, **_kwargs):
        self.submit_attempts += 1
        raise AssertionError("submit must not be admitted")


class _AssemblyModule:
    settings = SimpleNamespace()

    def __init__(self, transcriber) -> None:
        self._transcriber = transcriber

    def TranscriptionConfig(self, **_kwargs):
        return object()

    def Transcriber(self):
        return self._transcriber

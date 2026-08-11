"""Explicit Calendar authorization service boundaries."""

from __future__ import annotations

import threading
from types import SimpleNamespace

from meeting_memory.repo.calendar_oauth import CalendarAuthorizationUncertain
from meeting_memory.service.calendar_authorization import CalendarAuthorizationService
from meeting_memory.types.calendar_authorization import CalendarAuthorizationState


def test_authorization_is_explicit_bounded_and_does_not_query_calendar(tmp_path) -> None:
    credentials = tmp_path / "credentials.json"
    credentials.write_text("{}", encoding="utf-8")
    client = FakeClient()
    service = CalendarAuthorizationService(
        configuration_loader=lambda _use: SimpleNamespace(
            calendar_auth=SimpleNamespace(credentials_file=credentials)
        ),
        client_factory=lambda _config: client,
        timeout_seconds=41,
    )

    outcome = service.authorize()

    assert outcome.state is CalendarAuthorizationState.AUTHORIZED
    assert client.timeouts == [41]
    assert client.calendar_queries == 0


def test_authorization_is_single_flight(tmp_path) -> None:
    credentials = tmp_path / "credentials.json"
    credentials.write_text("{}", encoding="utf-8")
    entered = threading.Event()
    release = threading.Event()
    client = FakeClient(entered=entered, release=release)
    service = CalendarAuthorizationService(
        configuration_loader=lambda _use: SimpleNamespace(
            calendar_auth=SimpleNamespace(credentials_file=credentials)
        ),
        client_factory=lambda _config: client,
    )
    first: list[object] = []
    worker = threading.Thread(target=lambda: first.append(service.authorize()))
    worker.start()
    assert entered.wait(timeout=1)

    second = service.authorize()
    release.set()
    worker.join(timeout=1)

    assert second.state is CalendarAuthorizationState.ALREADY_IN_PROGRESS
    assert "progress" in second.summary
    assert first[0].state is CalendarAuthorizationState.AUTHORIZED


def test_authorization_uncertainty_never_exposes_exception() -> None:
    client = FakeClient(uncertain=True)
    service = CalendarAuthorizationService(
        configuration_loader=lambda _use: SimpleNamespace(
            calendar_auth=SimpleNamespace(credentials_file=ExistingPath())
        ),
        client_factory=lambda _config: client,
    )

    outcome = service.authorize()

    assert outcome.state is CalendarAuthorizationState.AUTHORIZATION_UNCERTAIN
    assert "token-secret-sentinel" not in repr(outcome)


class ExistingPath:
    def is_file(self) -> bool:
        return True


class FakeClient:
    def __init__(self, *, entered=None, release=None, uncertain=False) -> None:
        self.entered = entered
        self.release = release
        self.uncertain = uncertain
        self.timeouts: list[int] = []
        self.calendar_queries = 0

    def authenticate(self, *, timeout_seconds: int) -> None:
        self.timeouts.append(timeout_seconds)
        if self.entered is not None:
            self.entered.set()
            self.release.wait(timeout=2)
        if self.uncertain:
            raise CalendarAuthorizationUncertain("token-secret-sentinel")

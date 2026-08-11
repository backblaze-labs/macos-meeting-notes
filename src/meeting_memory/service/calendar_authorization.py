"""Explicit single-flight Calendar OAuth orchestration for worker threads."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Protocol

from meeting_memory.config.runtime import CalendarAuthConfig
from meeting_memory.repo.calendar_client import GoogleCalendarClient
from meeting_memory.repo.calendar_oauth import CalendarAuthorizationUncertain
from meeting_memory.service.configuration_loader import load_configuration
from meeting_memory.types.calendar_authorization import (
    CalendarAuthorizationOutcome,
    CalendarAuthorizationState,
)
from meeting_memory.types.configuration_resolution import ConfigurationUse


class CalendarAuthenticator(Protocol):
    def authenticate(self, *, timeout_seconds: int):
        raise NotImplementedError


def _client(config: CalendarAuthConfig) -> CalendarAuthenticator:
    return GoogleCalendarClient(
        credentials_file=config.credentials_file,
        calendar_id=config.calendar_id,
        known_speakers=config.known_speakers,
    )


class CalendarAuthorizationService:
    """Run browser/network authorization only after an explicit caller action."""

    def __init__(
        self,
        *,
        configuration_loader: Callable = load_configuration,
        client_factory: Callable[[CalendarAuthConfig], CalendarAuthenticator] = _client,
        timeout_seconds: int = 180,
    ) -> None:
        self._load = configuration_loader
        self._client_factory = client_factory
        self._timeout_seconds = timeout_seconds
        self._lock = threading.Lock()

    def authorize(self) -> CalendarAuthorizationOutcome:
        if not self._lock.acquire(blocking=False):
            return _outcome(CalendarAuthorizationState.ALREADY_IN_PROGRESS)
        try:
            configuration = self._load(ConfigurationUse.AUTH)
            config = configuration.calendar_auth
            if config is None:
                return _outcome(CalendarAuthorizationState.REJECTED)
            client = self._client_factory(config)
            client.authenticate(timeout_seconds=self._timeout_seconds)
            return _outcome(CalendarAuthorizationState.AUTHORIZED)
        except CalendarAuthorizationUncertain:
            return _outcome(CalendarAuthorizationState.AUTHORIZATION_UNCERTAIN)
        except Exception:
            return _outcome(CalendarAuthorizationState.FAILED)
        finally:
            self._lock.release()


def _outcome(state: CalendarAuthorizationState) -> CalendarAuthorizationOutcome:
    messages = {
        CalendarAuthorizationState.AUTHORIZED: (
            "Calendar authorization saved.",
            "Restart Meeting Memory to begin read-only polling.",
        ),
        CalendarAuthorizationState.ALREADY_IN_PROGRESS: (
            "Calendar authorization is already in progress.",
            "Finish or cancel the open browser authorization before trying again.",
        ),
        CalendarAuthorizationState.REJECTED: (
            "Calendar authorization did not start.",
            "Enable Calendar and choose a valid OAuth credentials file first.",
        ),
        CalendarAuthorizationState.AUTHORIZATION_UNCERTAIN: (
            "Calendar authorization may be saved.",
            "Restart and check setup before trying again.",
        ),
        CalendarAuthorizationState.FAILED: (
            "Calendar authorization failed.",
            "Check setup and try the explicit authorization action again.",
        ),
    }
    summary, action = messages[state]
    return CalendarAuthorizationOutcome(state, summary, action)

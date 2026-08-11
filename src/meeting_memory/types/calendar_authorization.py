"""Sanitized outcomes for explicit Google Calendar authorization."""

from dataclasses import dataclass
from enum import StrEnum


class CalendarAuthorizationState(StrEnum):
    AUTHORIZED = "authorized"
    ALREADY_IN_PROGRESS = "already_in_progress"
    REJECTED = "rejected"
    AUTHORIZATION_UNCERTAIN = "authorization_uncertain"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class CalendarAuthorizationOutcome:
    state: CalendarAuthorizationState
    summary: str
    action: str

    def __post_init__(self) -> None:
        if not isinstance(self.state, CalendarAuthorizationState):
            raise ValueError("authorization outcome requires typed state")
        if not self.summary.strip() or not self.action.strip():
            raise ValueError("authorization outcome requires safe text")

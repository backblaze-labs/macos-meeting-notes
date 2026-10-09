"""Speaker-related boundary data."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SpeakerSuggestion:
    """Unconfirmed provider proposal, without an identity-confidence score."""

    label: str
    name: str
    evidence: str = ""


@dataclass(frozen=True)
class SpeakerIdentificationResult:
    suggestions: tuple[SpeakerSuggestion, ...]


@dataclass(frozen=True)
class KnownSpeaker:
    """Configured person whose Calendar attendee identity can be normalized."""

    name: str
    matches: tuple[str, ...] = ()
    description: str = ""

    def __post_init__(self) -> None:
        name = self.name.strip()
        raw_matches = (self.matches,) if isinstance(self.matches, str) else self.matches
        matches = tuple(str(value).strip() for value in raw_matches if str(value).strip())
        if not name:
            raise ValueError("known speaker name must not be blank")
        if not isinstance(self.description, str) or len(self.description.strip()) > 300:
            raise ValueError("known speaker description must be text at most 300 characters")
        object.__setattr__(self, "description", self.description.strip())
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "matches", matches)


@dataclass(frozen=True)
class SpeakerUtterance:
    label: str
    text: str


@dataclass(frozen=True)
class SpeakerIdentificationRequest:
    utterances: tuple[SpeakerUtterance, ...]
    people: tuple[KnownSpeaker, ...]

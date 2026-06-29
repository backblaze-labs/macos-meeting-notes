"""Speaker-related boundary data."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KnownSpeaker:
    """Configured person whose Calendar attendee identity can be normalized."""

    name: str
    matches: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        name = self.name.strip()
        raw_matches = (self.matches,) if isinstance(self.matches, str) else self.matches
        matches = tuple(str(value).strip() for value in raw_matches if str(value).strip())
        if not name:
            raise ValueError("known speaker name must not be blank")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "matches", matches)

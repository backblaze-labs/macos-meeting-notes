"""Local people-base drafts and sanitized worker events."""

from dataclasses import dataclass, field

from meeting_memory.types.speakers import KnownSpeaker


@dataclass(frozen=True)
class PersonHistory:
    name: str
    quotes: tuple[str, ...] = field(default=(), repr=False)


@dataclass(frozen=True)
class SpeakerHistory:
    people: tuple[PersonHistory, ...] = ()
    meetings: int = 0
    scanned: int = 0


@dataclass(frozen=True)
class KnowledgeDraft:
    token: str
    people: tuple[KnownSpeaker, ...]
    history: SpeakerHistory = field(repr=False)
    message: str = ""
    history_included: bool = False


@dataclass(frozen=True)
class PersonTopic:
    name: str
    description: str
    evidence: str


@dataclass(frozen=True)
class KnowledgeDraftReady:
    draft: KnowledgeDraft


@dataclass(frozen=True)
class KnowledgeOffer:
    names: tuple[str, ...]
    initial: bool = False


@dataclass(frozen=True)
class KnowledgeFinished:
    message: str

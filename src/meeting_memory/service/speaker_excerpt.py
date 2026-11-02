"""Bounded diarized excerpts balanced across voices, with chronological context."""

import re
from collections import defaultdict

from meeting_memory.types.speakers import SpeakerUtterance

MAX_SPEAKER_EXCERPT_CHARS = 60_000
LINE = re.compile(r"^\*\*(?P<label>[^*]+)\*\* \(\d+:\d\d:\d\d\): (?P<text>.+)$", re.MULTILINE)
WORK_TERMS = re.compile(
    r"\b(?:work(?:s|ed|ing)?|build(?:s|ing)?|built|implement(?:s|ed|ing|ation)?|"
    r"test(?:s|ed|ing)?|review(?:s|ed|ing)?|"
    r"project|release(?:s|d)?|integration|dashboard|deploy(?:s|ed|ing|ment)?|documentation|"
    r"trabajando|pruebas|proyecto|integraci[oó]n)\b",
    re.IGNORECASE,
)


def substantive_rank(text: str) -> tuple[int, int]:
    """Prefer useful work passages, without treating topics as identity evidence."""
    words = text.split()
    return (min(4, len(WORK_TERMS.findall(text))), min(len(words), 100))


def speaker_excerpt(body: str) -> tuple[SpeakerUtterance, ...]:
    turns = tuple(
        SpeakerUtterance(match.group("label"), match.group("text")) for match in LINE.finditer(body)
    )
    costs = [len(turn.label) + len(turn.text) + 20 for turn in turns]
    if sum(costs) <= MAX_SPEAKER_EXCERPT_CHARS:
        return turns
    by_label = defaultdict(list)
    for index, turn in enumerate(turns):
        by_label[turn.label].append(index)
    ranked = [
        sorted(indices, key=lambda i: substantive_rank(turns[i].text), reverse=True)
        for indices in by_label.values()
    ]
    selected, size = set(), 0
    share = MAX_SPEAKER_EXCERPT_CHARS // max(1, len(ranked))
    # Reserve a first useful passage per voice before a frequent speaker can fill it.
    for indices in ranked:
        for index in indices:
            context = {index, max(0, index - 1)} - selected
            cost = sum(costs[i] for i in context)
            if cost <= share and size + cost <= MAX_SPEAKER_EXCERPT_CHARS:
                selected.update(context)
                size += cost
                break
    for position in range(max(map(len, ranked), default=0)):
        for indices in ranked:
            if position < len(indices):
                index = indices[position]
                if index not in selected and size + costs[index] <= MAX_SPEAKER_EXCERPT_CHARS:
                    selected.add(index)
                    size += costs[index]
    # Retain whole utterances and original order for named transitions.
    return tuple(turn for index, turn in enumerate(turns) if index in selected)

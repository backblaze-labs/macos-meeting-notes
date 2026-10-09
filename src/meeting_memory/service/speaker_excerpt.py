"""Bounded diarized excerpt containing no transcript frontmatter or provider IDs."""

import re

from meeting_memory.types.speakers import SpeakerUtterance

MAX_SPEAKER_EXCERPT_CHARS = 60_000
LINE = re.compile(r"^\*\*(?P<label>[^*]+)\*\* \(\d+:\d\d:\d\d\): (?P<text>.+)$", re.MULTILINE)


def speaker_excerpt(body: str) -> tuple[SpeakerUtterance, ...]:
    excerpt = []
    size = 0
    for match in LINE.finditer(body):
        label, text = match.group("label"), match.group("text")
        cost = len(label) + len(text) + 20
        if size + cost > MAX_SPEAKER_EXCERPT_CHARS:
            break
        excerpt.append(SpeakerUtterance(label, text))
        size += cost
    return tuple(excerpt)

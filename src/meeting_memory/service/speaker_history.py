"""Bounded, read-only harvesting of explicitly confirmed speaker identities."""

import os
import re
import stat
from pathlib import Path

from meeting_memory.service.frontmatter import split_frontmatter
from meeting_memory.service.ownership import classify_ownership, map_speaker_status
from meeting_memory.service.pinned_fs import open_directory_tree
from meeting_memory.service.speaker_excerpt import LINE
from meeting_memory.types.artifacts import ArtifactOwnership
from meeting_memory.types.speaker_knowledge import PersonHistory, SpeakerHistory

MAX_HISTORY_MEETINGS = 20
MAX_HISTORY_FOLDERS = 200
MAX_HISTORY_BYTES = 2_097_152
MAX_PERSON_CHARS = 4_000
MAX_TOTAL_CHARS = 60_000
ANONYMOUS = re.compile(r"^(?:Speaker |speaker_)[A-Z]+$", re.IGNORECASE)


def harvest_speaker_history(root: Path, only: Path | None = None) -> SpeakerHistory:
    collected: dict[str, list[str]] = {}
    count = scanned = 0
    try:
        root_fd = open_directory_tree(root.expanduser())
    except (OSError, ValueError):
        return SpeakerHistory()
    try:
        entries = [only.name] if only is not None else sorted(os.listdir(root_fd), reverse=True)
        for entry in entries[:MAX_HISTORY_FOLDERS]:
            scanned += 1
            try:
                markdown = _read_transcript(root_fd, entry)
                frontmatter, body = split_frontmatter(markdown)
                ownership = classify_ownership(frontmatter)
                if ownership is ArtifactOwnership.FOREIGN:
                    continue
                if map_speaker_status(frontmatter, ownership) != "confirmed":
                    continue
                aliases = frontmatter.get("speaker_aliases")
                if not isinstance(aliases, dict):
                    continue
                names = tuple(
                    dict.fromkeys(
                        name.strip()
                        for label, name in aliases.items()
                        if isinstance(name, str)
                        and name.strip()
                        and name != label
                        and not ANONYMOUS.fullmatch(name.strip())
                    )
                )
                if not names:
                    continue
                count += 1
                for name in names:
                    collected.setdefault(name, [])
                for match in LINE.finditer(body):
                    label, text = match.group("label"), match.group("text")
                    person = aliases.get(label, label)
                    if person in names and sum(map(len, collected[person])) < MAX_PERSON_CHARS:
                        collected[person].append(text[:MAX_PERSON_CHARS])
                if count >= MAX_HISTORY_MEETINGS:
                    break
            except (OSError, ValueError, UnicodeError):
                continue
    finally:
        os.close(root_fd)
    budget = min(MAX_PERSON_CHARS, MAX_TOTAL_CHARS // max(1, len(collected)))
    people = []
    for name, quotes in collected.items():
        bounded, size = [], 0
        for quote in quotes:
            excerpt = quote[: max(0, budget - size)]
            if excerpt:
                bounded.append(excerpt)
                size += len(excerpt)
        people.append(PersonHistory(name, tuple(bounded)))
    return SpeakerHistory(tuple(people), count, scanned)


def _read_transcript(root_fd: int, entry: str) -> str:
    directory = os.open(entry, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
    descriptor = -1
    try:
        descriptor = os.open(
            "transcript.md", os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=directory
        )
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_HISTORY_BYTES:
            raise ValueError("History transcript is not a bounded regular file")
        content = bytearray()
        while chunk := os.read(descriptor, min(65_536, MAX_HISTORY_BYTES + 1 - len(content))):
            content.extend(chunk)
            if len(content) > MAX_HISTORY_BYTES:
                raise ValueError("History transcript exceeds size limit")
        return content.decode("utf-8")
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(directory)

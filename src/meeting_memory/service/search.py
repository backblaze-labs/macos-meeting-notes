"""Local full-text search for stored meeting markdown files."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from meeting_memory.service.ownership import inspect_meeting_snapshot


@dataclass(frozen=True)
class MeetingSearchResult:
    slug: str
    title: str
    started_at: datetime
    path: Path
    excerpt: str


def search_meetings(
    meetings_dir: Path,
    query: str,
    *,
    limit: int = 20,
    excerpt_radius: int = 80,
) -> list[MeetingSearchResult]:
    """Search meeting markdown files by case-insensitive query terms."""

    terms = _query_terms(query)
    expanded_dir = meetings_dir.expanduser()
    if not terms or limit <= 0 or not expanded_dir.exists():
        return []

    results: list[MeetingSearchResult] = []
    for meeting_dir in expanded_dir.iterdir():
        snapshot = inspect_meeting_snapshot(meeting_dir)
        if snapshot is None:
            continue

        result = _search_one(
            snapshot.artifact.transcript_path,
            snapshot.frontmatter,
            snapshot.body,
            terms,
            excerpt_radius,
        )
        if result is not None:
            results.append(result)

    return sorted(results, key=lambda item: item.started_at, reverse=True)[:limit]


def _search_one(
    markdown_path: Path,
    frontmatter: dict[str, object],
    body: str,
    terms: tuple[str, ...],
    excerpt_radius: int,
) -> MeetingSearchResult | None:
    searchable = _normalize_search_text(f"{frontmatter.get('calendar_title', '')}\n{body}")

    if not all(term in searchable.casefold() for term in terms):
        return None

    try:
        started_at = datetime.fromisoformat(str(frontmatter["date"]))
    except (KeyError, ValueError):
        return None

    slug = str(frontmatter.get("id") or markdown_path.parent.name)
    title = str(frontmatter.get("calendar_title") or "Untitled")
    return MeetingSearchResult(
        slug=slug,
        title=title,
        started_at=started_at,
        path=markdown_path,
        excerpt=_excerpt(searchable, terms, excerpt_radius),
    )


def _query_terms(query: str) -> tuple[str, ...]:
    return tuple(term.casefold() for term in re.findall(r"\S+", query.strip()))


def _normalize_search_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _excerpt(text: str, terms: tuple[str, ...], radius: int) -> str:
    lower_text = text.casefold()
    matches = [
        (index, len(term)) for term in terms if (index := lower_text.find(term)) >= 0
    ]
    first_match, match_length = min(matches, default=(0, 0))
    safe_radius = max(radius, 0)
    start = max(0, first_match - safe_radius)
    end = min(len(text), first_match + match_length + safe_radius)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text) else ""
    return f"{prefix}{text[start:end].strip()}{suffix}"

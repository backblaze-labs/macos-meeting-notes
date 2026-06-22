"""Local transcript review and derived-notes generation."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Protocol

from meeting_memory.service.frontmatter import dump_frontmatter, split_frontmatter
from meeting_memory.service.markdown import render_notes_markdown
from meeting_memory.service.storage import (
    NOTES_MARKDOWN,
    TRANSCRIPT_MARKDOWN,
    is_ours,
    read_frontmatter,
)
from meeting_memory.types.meeting import MeetingMeta, RecentMeeting
from meeting_memory.types.summary import SummaryResult
from meeting_memory.types.transcript import SpeakerReviewState

SPEAKER_LABEL_RE = re.compile(r"^\*\*(?P<label>[^*]+)\*\*", re.MULTILINE)
TRANSCRIPT_LINE_RE = re.compile(
    r"^\*\*(?P<label>[^*]+)\*\* \(\d+:\d\d:\d\d\): (?P<text>.+)$",
    re.MULTILINE,
)
PARTICIPANTS_RE = re.compile(r"^\*\*Participants:\*\* .*$", re.MULTILINE)


class SummarizerClient(Protocol):
    def summarize(self, transcript_text: str) -> SummaryResult:
        """Summarize reviewed transcript text."""


def resolve_transcript_path(path: Path) -> Path:
    candidate = path.expanduser()
    if candidate.is_dir():
        candidate = candidate / TRANSCRIPT_MARKDOWN
    if not candidate.exists():
        raise FileNotFoundError(f"transcript not found: {candidate}")
    return candidate


def load_speaker_review(path: Path) -> SpeakerReviewState:
    transcript_path = resolve_transcript_path(path)
    markdown = transcript_path.read_text(encoding="utf-8")
    frontmatter, body = split_frontmatter(markdown)
    return SpeakerReviewState(
        meeting_directory=transcript_path.parent,
        transcript_path=transcript_path,
        speaker_labels=_speaker_labels(frontmatter, body),
        speaker_candidates=_string_list(frontmatter.get("speaker_candidates")),
        speaker_aliases=_optional_aliases(frontmatter.get("speaker_aliases")),
        speaker_status=str(frontmatter.get("speaker_status") or "needs_review"),
        speaker_longest_lines=_speaker_longest_lines(body),
    )


def confirm_speaker_aliases(path: Path, aliases: Mapping[str, str]) -> Path:
    state = load_speaker_review(path)
    cleaned = _clean_aliases(aliases)
    missing = [label for label in state.speaker_labels if label not in cleaned]
    if missing:
        raise ValueError(f"missing aliases for: {', '.join(missing)}")

    markdown = state.transcript_path.read_text(encoding="utf-8")
    frontmatter, body = split_frontmatter(markdown)
    frontmatter["speaker_aliases"] = {label: cleaned[label] for label in state.speaker_labels}
    state.transcript_path.write_text(
        f"{dump_frontmatter(frontmatter)}\n{body}",
        encoding="utf-8",
    )
    return relabel_transcript(state.transcript_path)


def relabel_transcript(path: Path) -> Path:
    transcript_path = resolve_transcript_path(path)
    markdown = transcript_path.read_text(encoding="utf-8")
    frontmatter, body = split_frontmatter(markdown)
    aliases = _speaker_aliases(frontmatter)
    participants = _mapped_participants(frontmatter, aliases)
    relabeled_body = SPEAKER_LABEL_RE.sub(lambda match: _replace_label(match, aliases), body)
    relabeled_body = PARTICIPANTS_RE.sub(
        f"**Participants:** {', '.join(participants) or '_None identified._'}",
        relabeled_body,
    )

    frontmatter["participants"] = participants
    frontmatter["speaker_aliases"] = aliases
    frontmatter["speaker_status"] = "confirmed"
    transcript_path.write_text(
        f"{dump_frontmatter(frontmatter)}\n{relabeled_body}",
        encoding="utf-8",
    )
    return transcript_path


def list_speaker_review_meetings(meetings_dir: Path, limit: int = 5) -> list[RecentMeeting]:
    if not meetings_dir.exists():
        return []

    meetings: list[RecentMeeting] = []
    for meeting_dir in meetings_dir.iterdir():
        if not meeting_dir.is_dir() or not is_ours(meeting_dir):
            continue
        transcript_path = meeting_dir / TRANSCRIPT_MARKDOWN
        try:
            state = load_speaker_review(transcript_path)
            frontmatter = read_frontmatter(transcript_path)
        except (OSError, ValueError):
            continue
        if state.speaker_status == "confirmed" or not state.speaker_labels:
            continue
        meetings.append(_recent_from_frontmatter(meeting_dir, transcript_path, frontmatter))

    return sorted(meetings, key=lambda item: item.started_at, reverse=True)[:limit]


def generate_notes_from_transcript(path: Path, summarizer: SummarizerClient) -> Path:
    transcript_path = resolve_transcript_path(path)
    markdown = transcript_path.read_text(encoding="utf-8")
    frontmatter, body = split_frontmatter(markdown)
    if frontmatter.get("speaker_status") != "confirmed":
        raise ValueError("speaker aliases must be confirmed before generating notes")

    summary = _summarize(summarizer, body)
    notes_path = transcript_path.parent / NOTES_MARKDOWN
    notes_path.write_text(
        render_notes_markdown(
            _meta_from_frontmatter(frontmatter),
            summary,
            source_transcript=TRANSCRIPT_MARKDOWN,
            speaker_status=str(frontmatter.get("speaker_status") or "confirmed"),
        ),
        encoding="utf-8",
    )
    return notes_path


def _speaker_aliases(frontmatter: dict[str, object]) -> dict[str, str]:
    raw_aliases = frontmatter.get("speaker_aliases")
    if not isinstance(raw_aliases, dict):
        raise ValueError("speaker_aliases must be a frontmatter object")

    aliases = {
        str(label).strip(): str(alias).strip()
        for label, alias in raw_aliases.items()
        if str(label).strip() and str(alias).strip()
    }
    if not aliases:
        raise ValueError("speaker_aliases must contain at least one mapping")
    return aliases


def _optional_aliases(raw_aliases: object) -> dict[str, str]:
    if not isinstance(raw_aliases, dict):
        return {}
    return _clean_aliases(raw_aliases)


def _clean_aliases(aliases: Mapping[str, str]) -> dict[str, str]:
    return {
        str(label).strip(): str(alias).strip()
        for label, alias in aliases.items()
        if str(label).strip() and str(alias).strip()
    }


def _speaker_labels(frontmatter: dict[str, object], body: str) -> tuple[str, ...]:
    labels = _string_list(frontmatter.get("participants"))
    if not labels:
        labels = tuple(match.group("label") for match in TRANSCRIPT_LINE_RE.finditer(body))
    return tuple(dict.fromkeys(labels))


def _speaker_longest_lines(body: str) -> dict[str, str]:
    longest: dict[str, str] = {}
    for match in TRANSCRIPT_LINE_RE.finditer(body):
        label = match.group("label").strip()
        text = match.group("text").strip()
        if label and text and len(text) > len(longest.get(label, "")):
            longest[label] = text
    return longest


def _string_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _recent_from_frontmatter(
    meeting_dir: Path,
    markdown_path: Path,
    frontmatter: dict[str, object],
) -> RecentMeeting:
    return RecentMeeting(
        slug=str(frontmatter["id"]),
        calendar_title=str(frontmatter["calendar_title"]),
        started_at=datetime.fromisoformat(str(frontmatter["date"])),
        directory=meeting_dir,
        markdown_path=markdown_path,
    )


def _replace_label(match: re.Match[str], aliases: dict[str, str]) -> str:
    label = match.group("label")
    alias = aliases.get(label)
    if alias is None:
        return match.group(0)
    return f"**{alias}**"


def _mapped_participants(
    frontmatter: dict[str, object],
    aliases: dict[str, str],
) -> list[str]:
    raw_participants = frontmatter.get("participants")
    if not isinstance(raw_participants, list):
        return list(dict.fromkeys(aliases.values()))

    mapped: dict[str, None] = {}
    for participant in raw_participants:
        label = str(participant)
        mapped.setdefault(aliases.get(label, label), None)
    return list(mapped)


def _summarize(summarizer: SummarizerClient, transcript_text: str) -> SummaryResult:
    try:
        return summarizer.summarize(transcript_text)
    except Exception:
        return SummaryResult.failed()


def _meta_from_frontmatter(frontmatter: dict[str, object]) -> MeetingMeta:
    return MeetingMeta(
        slug=str(frontmatter["id"]),
        started_at=datetime.fromisoformat(str(frontmatter["date"])),
        calendar_title=str(frontmatter["calendar_title"]),
        duration_minutes=int(frontmatter["duration_minutes"]),
    )

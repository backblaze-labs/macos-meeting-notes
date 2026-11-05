"""Atomic schema-v2 speaker confirmation and transcript-body relabeling."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from meeting_memory.service.frontmatter import merge_frontmatter_fields, split_frontmatter
from meeting_memory.service.meeting_document import (
    MeetingDocument,
    open_meeting_document,
    validate_meeting_document,
)
from meeting_memory.service.meeting_locks import meeting_lock
from meeting_memory.service.meeting_state import MeetingStateConflict
from meeting_memory.service.transcript_turns import coalesce_transcript_turns
from meeting_memory.types.capabilities import MeetingJobState
from meeting_memory.types.transcript import is_unknown_speaker

SPEAKER_LABEL_RE = re.compile(r"^\*\*(?P<label>[^*]+)\*\*(?= \(\d+:\d\d:\d\d\): )", re.MULTILINE)
TRANSCRIPT_LINE_RE = re.compile(
    r"^\*\*(?P<label>[^*]+)\*\* \(\d+:\d\d:\d\d\): (?P<text>.+)$",
    re.MULTILINE,
)
PARTICIPANTS_RE = re.compile(r"^\*\*Participants:\*\* .*$", re.MULTILINE)


def confirm_v2_speakers(
    meetings_dir: Path,
    meeting_dir: Path,
    aliases: Mapping[str, str],
    *,
    expected_status: str | None = None,
    keep_labels: bool = False,
) -> Path:
    """Relabel body and owned fields with one locked atomic replacement."""

    validate_meeting_document(meetings_dir, meeting_dir)
    with meeting_lock(meetings_dir, meeting_dir.name):
        with open_meeting_document(meetings_dir, meeting_dir) as document:
            frontmatter, body = split_frontmatter(document.text)
            return _confirm_locked(
                document,
                frontmatter,
                body,
                aliases,
                expected_status,
                keep_labels,
            )


def _confirm_locked(
    document: MeetingDocument,
    frontmatter: dict[str, object],
    body: str,
    aliases: Mapping[str, str],
    expected_status: str | None,
    keep_labels: bool,
) -> Path:
    current_status = str(frontmatter.get("speaker_status") or "not_available")
    if expected_status is not None and current_status != expected_status:
        raise MeetingStateConflict(f"speaker state is {current_status}, expected {expected_status}")
    cleaned = _clean_aliases(aliases)
    if current_status == "confirmed":
        stored = _stored_aliases(frontmatter)
        if cleaned == stored:
            coalesced = coalesce_transcript_turns(body)
            if coalesced == body:
                return document.path / "transcript.md"
            return _publish_transcript(
                document, frontmatter, _replace_body(document.text, coalesced)
            )
        if stored or keep_labels or not cleaned:
            raise MeetingStateConflict("confirmed speaker aliases are terminal")
        # Labels were kept (a historical automatic Notes run, or an explicit Keep
        # Speaker Labels): the body still carries diarized labels, so one
        # later manual mapping is allowed. Named aliases stay terminal.
    elif current_status != "needs_review":
        raise MeetingStateConflict(f"speaker state is {current_status}, expected needs_review")
    labels = _transcript_labels(body)
    if not labels:
        raise ValueError("speaker confirmation requires transcript speaker labels")
    selected, stored_aliases = reviewed_speaker_names(labels, cleaned, keep_labels)

    participants = list(dict.fromkeys(selected.values()))
    relabeled = SPEAKER_LABEL_RE.sub(lambda match: _replace_label(match, selected), body)
    relabeled = PARTICIPANTS_RE.sub(
        f"**Participants:** {', '.join(participants) or '_None identified._'}",
        relabeled,
    )
    updated = _replace_body(
        merge_frontmatter_fields(
            document.text,
            {
                "participants": participants,
                "speaker_aliases": stored_aliases,
                "speaker_status": "confirmed",
            },
        ),
        coalesce_transcript_turns(relabeled),
    )
    return _publish_transcript(document, frontmatter, updated)


def _publish_transcript(document, frontmatter, updated) -> Path:
    if frontmatter.get("backup_status") == MeetingJobState.SUCCEEDED.value:
        revision = document.backup_revision(updated)
        if revision != frontmatter.get("backup_uploaded_revision"):
            updated = merge_frontmatter_fields(
                updated,
                {"backup_status": MeetingJobState.PENDING.value},
            )
    document.replace_transcript(updated)
    return document.path / "transcript.md"


def _transcript_labels(body: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(match.group("label") for match in TRANSCRIPT_LINE_RE.finditer(body)))


def _stored_aliases(frontmatter: dict[str, object]) -> dict[str, str]:
    raw = frontmatter.get("speaker_aliases")
    return _clean_aliases(raw) if isinstance(raw, dict) else {}


def reviewed_speaker_names(
    labels: tuple[str, ...],
    aliases: Mapping[str, str],
    keep_labels: bool,
) -> tuple[dict[str, str], dict[str, str]]:
    """Resolve displayed names separately from persisted user aliases."""
    cleaned = _clean_aliases(aliases)
    if keep_labels:
        if cleaned:
            raise ValueError("keeping speaker labels does not accept aliases")
        return {label: label for label in labels}, {}
    missing = [label for label in labels if not is_unknown_speaker(label) and label not in cleaned]
    if missing:
        raise ValueError(f"missing aliases for: {', '.join(missing)}")
    selected = {label: label if is_unknown_speaker(label) else cleaned[label] for label in labels}
    return selected, {
        label: name for label, name in selected.items() if not is_unknown_speaker(label)
    }


def _clean_aliases(aliases: Mapping[str, str]) -> dict[str, str]:
    return {
        str(label).strip(): str(alias).strip()
        for label, alias in aliases.items()
        if str(label).strip() and str(alias).strip()
    }


def _replace_label(match: re.Match[str], aliases: dict[str, str]) -> str:
    return f"**{aliases.get(match.group('label'), match.group('label'))}**"


def _replace_body(markdown: str, body: str) -> str:
    lines = markdown.splitlines(keepends=True)
    closing = next(
        index for index, line in enumerate(lines[1:], start=1) if line.rstrip("\r\n") == "---"
    )
    frontmatter = "".join(lines[: closing + 1]).rstrip("\r\n")
    return f"{frontmatter}\n{body}"

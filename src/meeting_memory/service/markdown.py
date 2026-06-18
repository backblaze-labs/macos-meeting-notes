"""Render local `meeting.md` files."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from meeting_memory.service.frontmatter import dump_frontmatter
from meeting_memory.service.speaker_mapping import apply_speaker_mapping
from meeting_memory.types.meeting import MeetingMeta
from meeting_memory.types.summary import ActionItem, SummaryResult
from meeting_memory.types.transcript import TranscriptResult


def render_meeting_markdown(
    meta: MeetingMeta,
    transcript: TranscriptResult,
    summary: SummaryResult,
    *,
    b2_audio: str | None = None,
    b2_transcript: str | None = None,
    b2_status: str = "pending",
    speaker_mapping: Mapping[str, str] | None = None,
) -> str:
    transcript = apply_speaker_mapping(transcript, speaker_mapping)
    frontmatter = dump_frontmatter(
        {
            "id": meta.slug,
            "date": meta.started_at.isoformat(),
            "duration_minutes": meta.duration_minutes,
            "calendar_title": meta.calendar_title,
            "participants": list(transcript.participants),
            "assemblyai_id": transcript.assemblyai_id,
            "summary_status": summary.status,
            "b2_audio": b2_audio,
            "b2_transcript": b2_transcript,
            "b2_status": b2_status,
        }
    )
    return "\n".join(
        [
            frontmatter,
            "",
            f"# {meta.calendar_title}",
            "",
            f"**Date:** {_human_date(meta.started_at)}",
            f"**Duration:** {meta.duration_minutes} minutes",
            f"**Participants:** {_participants(transcript)}",
            "",
            "## Summary",
            "",
            _summary_text(summary),
            "",
            "## Decisions",
            "",
            _decision_text(summary),
            "",
            "## Action Items",
            "",
            _action_item_text(summary),
            "",
            "## Transcript",
            "",
            _transcript_text(transcript),
            "",
        ]
    )


def _human_date(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M")


def _participants(transcript: TranscriptResult) -> str:
    return ", ".join(transcript.participants) or "_None identified._"


def _summary_text(summary: SummaryResult) -> str:
    if summary.status == "skipped":
        return "_Summarization skipped._"
    if summary.status == "failed":
        return "_Summarization failed._"
    return summary.summary or "_Summarization skipped._"


def _decision_text(summary: SummaryResult) -> str:
    if not summary.decisions:
        return "_None identified._"
    return "\n".join(f"- {decision}" for decision in summary.decisions)


def _action_item_text(summary: SummaryResult) -> str:
    if not summary.action_items:
        return "_None identified._"
    return "\n".join(_format_action_item(item) for item in summary.action_items)


def _format_action_item(item: ActionItem) -> str:
    owner = f"{item.owner}: " if item.owner else ""
    due = f" (Due: {item.due_date})" if item.due_date else ""
    return f"- [ ] {owner}{item.task}{due}"


def _transcript_text(transcript: TranscriptResult) -> str:
    if transcript.error:
        return f"_Transcription failed: {transcript.error}_"
    return "\n".join(
        f"**{segment.speaker_label}** ({segment.timestamp}): {segment.text}"
        for segment in transcript.segments
    )

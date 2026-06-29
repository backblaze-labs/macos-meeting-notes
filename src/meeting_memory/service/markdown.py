"""Render local meeting markdown artifacts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

from meeting_memory.service.frontmatter import dump_frontmatter
from meeting_memory.service.speaker_mapping import apply_speaker_mapping
from meeting_memory.types.meeting import MeetingMeta
from meeting_memory.types.summary import ActionItem, SummaryResult
from meeting_memory.types.transcript import TranscriptResult

TRANSCRIPT_FRONTMATTER_FIELDS = (
    "id",
    "date",
    "duration_minutes",
    "calendar_title",
    "participants",
    "assemblyai_id",
    "speaker_candidates",
    "speaker_aliases",
    "speaker_status",
    "b2_audio",
    "b2_transcript",
    "b2_status",
)

NOTES_FRONTMATTER_FIELDS = (
    "id",
    "date",
    "duration_minutes",
    "calendar_title",
    "source_transcript",
    "speaker_status",
    "summary_status",
)


def render_meeting_markdown(
    meta: MeetingMeta,
    transcript: TranscriptResult,
    summary: SummaryResult,
    *,
    b2_audio: str | None = None,
    b2_transcript: str | None = None,
    b2_status: str = "pending",
    speaker_aliases: Mapping[str, str] | None = None,
) -> str:
    return render_transcript_markdown(
        meta,
        transcript,
        speaker_aliases=speaker_aliases,
        b2_audio=b2_audio,
        b2_transcript=b2_transcript,
        b2_status=b2_status,
    )


def render_transcript_markdown(
    meta: MeetingMeta,
    transcript: TranscriptResult,
    *,
    speaker_aliases: Mapping[str, str] | None = None,
    speaker_candidates: Sequence[str] = (),
    speaker_status: str = "needs_review",
    b2_audio: str | None = None,
    b2_transcript: str | None = None,
    b2_status: str = "pending",
) -> str:
    aliases = _clean_aliases(speaker_aliases)
    rendered_transcript = apply_speaker_mapping(transcript, aliases)
    frontmatter = dump_frontmatter(
        {
            "id": meta.slug,
            "date": meta.started_at.isoformat(),
            "duration_minutes": meta.duration_minutes,
            "calendar_title": meta.calendar_title,
            "participants": list(rendered_transcript.participants),
            "assemblyai_id": transcript.assemblyai_id,
            "speaker_candidates": list(speaker_candidates),
            "speaker_aliases": aliases,
            "speaker_status": speaker_status,
            "b2_audio": b2_audio,
            "b2_transcript": b2_transcript,
            "b2_status": b2_status,
        },
        fields=TRANSCRIPT_FRONTMATTER_FIELDS,
    )
    return "\n".join(
        [
            frontmatter,
            "",
            "# Transcript",
            "",
            f"**Date:** {_human_date(meta.started_at)}",
            f"**Duration:** {meta.duration_minutes} minutes",
            f"**Participants:** {_participants(rendered_transcript)}",
            "",
            _transcript_text(rendered_transcript),
            "",
        ]
    )


def render_notes_markdown(
    meta: MeetingMeta,
    summary: SummaryResult,
    *,
    source_transcript: str = "transcript.md",
    speaker_status: str = "confirmed",
) -> str:
    frontmatter = dump_frontmatter(
        {
            "id": meta.slug,
            "date": meta.started_at.isoformat(),
            "duration_minutes": meta.duration_minutes,
            "calendar_title": meta.calendar_title,
            "source_transcript": source_transcript,
            "speaker_status": speaker_status,
            "summary_status": summary.status,
        },
        fields=NOTES_FRONTMATTER_FIELDS,
    )
    return "\n".join(
        [
            frontmatter,
            "",
            "# Meeting Notes",
            "",
            f"**Source:** {source_transcript}",
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


def _clean_aliases(speaker_aliases: Mapping[str, str] | None) -> dict[str, str]:
    if speaker_aliases is None:
        return {}
    return {
        str(label).strip(): str(alias).strip()
        for label, alias in speaker_aliases.items()
        if str(label).strip() and str(alias).strip()
    }

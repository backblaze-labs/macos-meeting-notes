"""Processing state boundary models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from meeting_memory.types.meeting import RecentMeeting

ProcessingAction = Literal["review_speakers", "generate_notes"]
ProcessingStage = Literal["speaker_review", "notes"]
ProcessingStatus = Literal["waiting", "failed", "skipped"]


@dataclass(frozen=True)
class ProcessingTask:
    meeting: RecentMeeting
    stage: ProcessingStage
    action: ProcessingAction
    status: ProcessingStatus
    label: str

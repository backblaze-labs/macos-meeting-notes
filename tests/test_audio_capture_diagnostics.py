"""Capture diagnostics remain actionable during and after a recording."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from meeting_memory.repo.native_audio_health import HelperStatus
from meeting_memory.service.frontmatter import split_frontmatter
from meeting_memory.service.meeting_state import MeetingStateStore
from meeting_memory.service.meeting_store import MeetingStore
from meeting_memory.service.recorder import RecorderService
from meeting_memory.service.recovery_index import discover_indexed_recoveries
from meeting_memory.service.transcript_state import TranscriptStateStore
from meeting_memory.types.artifacts import MeetingJob
from meeting_memory.types.audio import CaptureDiagnostics
from meeting_memory.types.capabilities import MeetingJobState
from meeting_memory.types.meeting import PostCommitPolicy
from meeting_memory.types.transcript import TranscriptResult, TranscriptSegment


def _event(
    event: str,
    *,
    elapsed: float = 50,
    system_callbacks: int = 10,
    microphone_callbacks: int = 10,
) -> dict[str, object]:
    return {
        "event": event,
        "mode": "full-meeting",
        "microphone": "Built-in Microphone",
        "elapsed_seconds": elapsed,
        "sources": {
            "system": {
                "callbacks": system_callbacks,
                "frames": system_callbacks * 1_600,
                "peak": 0.2 if system_callbacks else 0,
                "discarded_frames": 0,
                "first_callback_seconds": 0 if system_callbacks else None,
                "last_callback_seconds": elapsed if system_callbacks else None,
            },
            "microphone": {
                "callbacks": microphone_callbacks,
                "frames": microphone_callbacks * 1_600,
                "peak": 0.3 if microphone_callbacks else 0,
                "discarded_frames": 0,
                "first_callback_seconds": 0 if microphone_callbacks else None,
                "last_callback_seconds": elapsed if microphone_callbacks else None,
            },
        },
    }


def test_missing_source_warns_once_and_is_retained_in_final_diagnostics() -> None:
    status = HelperStatus()

    status.observe(_event("health", elapsed=10, system_callbacks=0))
    warning = status.next_warning()
    status.observe(_event("health", elapsed=15, system_callbacks=0))
    status.observe(_event("stopped", elapsed=20, system_callbacks=0))

    assert warning is not None
    assert warning.code == "system_missing"
    assert "Zoom/system" in warning.message
    assert status.next_warning() is None
    assert status.final_diagnostics() is not None
    assert status.final_diagnostics().warnings == ("system_missing",)


def test_silence_stall_and_discard_each_produce_specific_warnings() -> None:
    event = _event("health")
    sources = event["sources"]
    assert isinstance(sources, dict)
    system = sources["system"]
    assert isinstance(system, dict)
    system["peak"] = 0
    system["last_callback_seconds"] = 30
    system["discarded_frames"] = 1_600
    status = HelperStatus()

    status.observe(event)

    codes = []
    while warning := status.next_warning():
        codes.append(warning.code)
    assert codes == ["system_stalled", "system_timing_discard", "system_silent"]


def test_invalid_final_diagnostics_are_not_silently_accepted() -> None:
    status = HelperStatus()

    status.observe({"event": "stopped"})

    assert status.failure_message() == "native helper returned invalid final diagnostics"


class DiagnosticCapture:
    def __init__(self, _mode: str, output_path: Path) -> None:
        self.output_path = output_path
        self.output_path.write_bytes(b"RIFF" + b"\0" * 64)
        self.diagnostics: CaptureDiagnostics | None = None

    def stop(self) -> Path:
        self.diagnostics = CaptureDiagnostics.from_payload(_event("stopped"))
        return self.output_path


def test_final_diagnostics_survive_recovery_and_transcript_creation(tmp_path: Path) -> None:
    times = iter(
        [
            datetime(2026, 8, 20, 9, 0, tzinfo=UTC),
            datetime(2026, 8, 20, 9, 5, tzinfo=UTC),
        ]
    )
    recorder = RecorderService(
        temp_dir=tmp_path,
        now=lambda: next(times),
        capture_starter=DiagnosticCapture,
    )

    recorder.start("Back-to-back sync")
    result = recorder.stop()

    assert result is not None
    recovered = discover_indexed_recoveries(tmp_path)
    assert recovered[0].meta.capture_diagnostics == result.meta.capture_diagnostics
    payload = json.loads(recovered[0].index_path.read_text(encoding="utf-8"))
    assert payload["capture_diagnostics"]["status"] == "healthy"
    files = MeetingStore(tmp_path / "meetings").commit(
        result.audio_path,
        result.meta,
        PostCommitPolicy(transcription=True),
    )
    state = MeetingStateStore(files.directory.parent)
    state.transition_job(
        files.directory,
        MeetingJob.TRANSCRIPTION,
        MeetingJobState.PENDING,
        MeetingJobState.RUNNING,
    )
    TranscriptStateStore(files.directory.parent).succeed(
        files.directory,
        result.meta,
        TranscriptResult("job-1", (TranscriptSegment("A", 0, "Hello"),)),
    )
    frontmatter, _ = split_frontmatter(files.transcript_path.read_text(encoding="utf-8"))
    assert frontmatter["capture_status"] == "healthy"
    assert frontmatter["capture_diagnostics"]["sources"]["system"]["frames"] == 16_000

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
from meeting_memory.types.audio import CaptureDiagnostics, CaptureHealthWarning
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
                "largest_discarded_run": 0,
                "first_callback_seconds": 0 if system_callbacks else None,
                "last_callback_seconds": elapsed if system_callbacks else None,
            },
            "microphone": {
                "callbacks": microphone_callbacks,
                "frames": microphone_callbacks * 1_600,
                "peak": 0.3 if microphone_callbacks else 0,
                "discarded_frames": 0,
                "largest_discarded_run": 0,
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


def test_silence_stall_and_material_discard_produce_specific_warnings() -> None:
    event = _event("health", elapsed=95)
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


def test_quiet_call_start_does_not_warn_before_ninety_seconds() -> None:
    event = _event("health", elapsed=45)
    sources = event["sources"]
    assert isinstance(sources, dict)
    system = sources["system"]
    assert isinstance(system, dict)
    system["peak"] = 0
    status = HelperStatus()

    status.observe(event)

    assert status.next_warning() is None
    assert status.active_warning() is None


def test_recovered_system_audio_clears_live_and_final_warning() -> None:
    silent = _event("health", elapsed=95)
    silent_sources = silent["sources"]
    assert isinstance(silent_sources, dict)
    silent_system = silent_sources["system"]
    assert isinstance(silent_system, dict)
    silent_system["peak"] = 0
    status = HelperStatus()
    status.observe(silent)

    warning = status.next_warning()
    assert warning is not None
    assert warning.code == "system_silent"
    assert status.active_warning() == warning

    recovered = _event("health", elapsed=100)
    status.observe(recovered)
    status.observe(_event("stopped", elapsed=120))

    diagnostics = status.final_diagnostics()
    assert status.active_warning() is None
    assert diagnostics is not None
    assert diagnostics.status == "healthy"
    assert diagnostics.warnings == ()
    assert diagnostics.warning_history == ("system_silent",)


def test_recorder_clears_warning_when_native_source_recovers(tmp_path: Path) -> None:
    capture = RecoveringWarningCapture(tmp_path / "recording.wav")
    recorder = RecorderService(
        temp_dir=tmp_path,
        capture_starter=lambda _mode, _path: capture,
    )
    recorder.start("Product Sync")

    warning = recorder.check_health()
    assert warning is not None
    assert recorder.recording_warning == warning

    assert recorder.check_health() is None
    assert recorder.recording_warning is None


def test_small_distributed_microphone_trims_do_not_warn() -> None:
    event = _event("stopped", elapsed=1_598)
    sources = event["sources"]
    assert isinstance(sources, dict)
    microphone = sources["microphone"]
    assert isinstance(microphone, dict)
    microphone.update(
        callbacks=149_817,
        frames=25_568_752,
        discarded_frames=33_166,
        largest_discarded_run=1,
    )
    status = HelperStatus()

    status.observe(event)

    diagnostics = status.final_diagnostics()
    assert status.next_warning() is None
    assert diagnostics is not None
    assert diagnostics.status == "healthy"


def test_material_discard_warns_for_ratio_or_contiguous_burst() -> None:
    ratio_event = _event("health")
    ratio_sources = ratio_event["sources"]
    assert isinstance(ratio_sources, dict)
    ratio_system = ratio_sources["system"]
    assert isinstance(ratio_system, dict)
    ratio_system.update(frames=160_000, discarded_frames=1_600)
    ratio_status = HelperStatus()
    ratio_status.observe(ratio_event)

    burst_event = _event("health")
    burst_sources = burst_event["sources"]
    assert isinstance(burst_sources, dict)
    burst_system = burst_sources["system"]
    assert isinstance(burst_system, dict)
    burst_system.update(
        frames=16_000_000,
        discarded_frames=1_600,
        largest_discarded_run=1_600,
    )
    burst_status = HelperStatus()
    burst_status.observe(burst_event)

    assert ratio_status.next_warning().code == "system_timing_discard"
    assert burst_status.next_warning().code == "system_timing_discard"


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


class RecoveringWarningCapture:
    def __init__(self, output_path: Path) -> None:
        self.output_path = output_path
        self.output_path.write_bytes(b"RIFF" + b"\0" * 64)
        self._warning = CaptureHealthWarning("system_silent", "System audio is quiet.")
        self._poll = 0

    @property
    def active_warning(self) -> CaptureHealthWarning | None:
        return self._warning if self._poll == 1 else None

    def check_health(self) -> CaptureHealthWarning | None:
        self._poll += 1
        return self._warning if self._poll == 1 else None


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
    assert payload["capture_diagnostics"]["sources"]["system"]["largest_discarded_run"] == 0
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

import threading
from datetime import UTC, datetime
from pathlib import Path

from meeting_memory.service.meeting_state import MeetingStateConflict, MeetingStateStore
from meeting_memory.service.meeting_store import MeetingStore
from meeting_memory.service.transcript_state import TranscriptStateStore
from meeting_memory.types.artifacts import MeetingJob
from meeting_memory.types.capabilities import MeetingJobState
from meeting_memory.types.meeting import MeetingMeta, PostCommitPolicy


def test_provider_job_id_is_single_winner_compare_and_set(tmp_path: Path) -> None:
    meetings = tmp_path / "meetings"
    source = tmp_path / "audio.m4a"
    source.write_bytes(b"audio")
    meta = MeetingMeta(
        "2026-08-10_10-00_product-sync",
        datetime(2026, 8, 10, 10, tzinfo=UTC),
        "Product Sync",
    )
    files = MeetingStore(meetings).commit(
        source,
        meta,
        PostCommitPolicy(transcription=True),
    )
    MeetingStateStore(meetings).transition_job(
        files.directory,
        MeetingJob.TRANSCRIPTION,
        MeetingJobState.PENDING,
        MeetingJobState.RUNNING,
    )
    store = TranscriptStateStore(meetings)
    barrier = threading.Barrier(2)
    successes: list[str] = []
    conflicts: list[str] = []

    def compete(identifier: str) -> None:
        barrier.wait()
        try:
            store.record_job_id(files.directory, identifier)
            successes.append(identifier)
        except MeetingStateConflict:
            conflicts.append(identifier)

    workers = [threading.Thread(target=compete, args=(identifier,)) for identifier in ("a", "b")]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()

    assert len(successes) == 1
    assert len(conflicts) == 1
    text = files.transcript_path.read_text(encoding="utf-8")
    assert f'assemblyai_id: "{successes[0]}"' in text
    assert f'assemblyai_id: "{conflicts[0]}"' not in text


def test_provider_job_id_is_idempotent_for_same_worker(tmp_path: Path) -> None:
    meetings = tmp_path / "meetings"
    source = tmp_path / "audio.m4a"
    source.write_bytes(b"audio")
    files = MeetingStore(meetings).commit(
        source,
        MeetingMeta(
            "2026-08-10_10-00_sync",
            datetime(2026, 8, 10, 10, tzinfo=UTC),
            "Sync",
        ),
        PostCommitPolicy(transcription=True),
    )
    MeetingStateStore(meetings).transition_job(
        files.directory,
        MeetingJob.TRANSCRIPTION,
        MeetingJobState.PENDING,
        MeetingJobState.RUNNING,
    )
    store = TranscriptStateStore(meetings)
    store.record_job_id(files.directory, "job-1")
    before = files.transcript_path.read_bytes()

    store.record_job_id(files.directory, "job-1")

    assert files.transcript_path.read_bytes() == before

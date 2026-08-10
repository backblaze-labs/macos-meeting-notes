from datetime import UTC, datetime
from pathlib import Path

from meeting_memory.service import search, storage
from meeting_memory.service.meeting_store import MeetingStore
from meeting_memory.service.ownership import inspect_meeting_artifact, inspect_meeting_snapshot
from meeting_memory.service.search import search_meetings
from meeting_memory.service.storage import list_recent_meetings
from meeting_memory.types.capabilities import MeetingJobState
from meeting_memory.types.meeting import MeetingMeta


def test_providerless_v2_first_value_is_visible_and_foreign_markdown_is_not(
    tmp_path: Path,
) -> None:
    meetings = tmp_path / "meetings"
    audio = tmp_path / "source.m4a"
    audio.write_bytes(b"audio")
    files = MeetingStore(meetings).commit(
        audio,
        MeetingMeta(
            "2026-08-10_10-00_product-sync",
            datetime(2026, 8, 10, 10, tzinfo=UTC),
            "Product Sync",
        ),
    )
    foreign = meetings / "foreign"
    foreign.mkdir()
    (foreign / "transcript.md").write_text(
        "---\nid: foreign\ndate: 2026-08-10T10:00:00+00:00\n---\nsecret\n",
        encoding="utf-8",
    )

    artifact = inspect_meeting_artifact(files.directory)
    assert artifact is not None
    assert artifact.transcription_status is MeetingJobState.NOT_REQUESTED
    assert artifact.backup_status is MeetingJobState.NOT_REQUESTED
    assert [meeting.slug for meeting in list_recent_meetings(meetings)] == [files.meta.slug]
    assert [result.slug for result in search_meetings(meetings, "Product Sync")] == [
        files.meta.slug
    ]
    assert inspect_meeting_artifact(foreign) is None
    assert all(meeting.slug != "foreign" for meeting in list_recent_meetings(meetings))


def test_recent_and_search_never_reopen_a_swapped_meeting_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    meetings = tmp_path / "meetings"
    audio = tmp_path / "audio"
    audio.write_bytes(b"audio")
    files = MeetingStore(meetings).commit(
        audio,
        MeetingMeta(
            "2026-08-10_11-00_owned",
            datetime(2026, 8, 10, 11, tzinfo=UTC),
            "Owned Title",
        ),
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "recording.m4a").write_bytes(b"secret-audio")
    (outside / "transcript.md").write_text(
        "---\nid: leaked\ndate: 2026-08-10T12:00:00+00:00\n"
        "calendar_title: Outside Only\nassemblyai_id: legacy\n---\noutside-only",
        encoding="utf-8",
    )
    saved = meetings / "saved-owned"

    def swap_after_snapshot(path: Path):
        snapshot = inspect_meeting_snapshot(path)
        if path == files.directory:
            path.rename(saved)
            path.symlink_to(outside, target_is_directory=True)
        return snapshot

    monkeypatch.setattr(storage, "inspect_meeting_snapshot", swap_after_snapshot)
    assert [item.slug for item in list_recent_meetings(meetings)] == [files.meta.slug]
    files.directory.unlink()
    saved.rename(files.directory)

    monkeypatch.setattr(search, "inspect_meeting_snapshot", swap_after_snapshot)
    assert search_meetings(meetings, "outside-only") == []

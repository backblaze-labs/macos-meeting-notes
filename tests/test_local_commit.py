"""Tests for the inactive atomic local-first meeting store."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

from meeting_memory.service.frontmatter import split_frontmatter
from meeting_memory.service.meeting_store import CommitDurabilityUncertain, MeetingStore
from meeting_memory.types.meeting import MeetingMeta, PostCommitPolicy


def test_commit_publishes_complete_files_before_returning(tmp_path: Path) -> None:
    audio = _audio(tmp_path)
    observed: list[str] = []

    def publish(source: Path, destination: Path) -> None:
        observed.extend(path.name for path in source.iterdir())
        assert (source / "recording.m4a").read_bytes() == b"m4a-audio"
        assert (source / "transcript.md").read_text(encoding="utf-8").endswith("\n")
        source.rename(destination)

    files = MeetingStore(tmp_path / "meetings", publisher=publish).commit(
        audio,
        _meta(),
        PostCommitPolicy(transcription=True, backup=False),
    )

    assert sorted(observed) == ["recording.m4a", "transcript.md"]
    assert sorted(path.name for path in files.directory.iterdir()) == [
        "recording.m4a",
        "transcript.md",
    ]
    frontmatter, _ = split_frontmatter(files.transcript_path.read_text(encoding="utf-8"))
    assert frontmatter["id"] == files.directory.name == files.meta.slug
    assert frontmatter["transcription_status"] == "pending"
    assert frontmatter["backup_status"] == "not_requested"
    assert files.audio_path.open("rb").read() == b"m4a-audio"


def test_first_commit_flushes_each_new_directory_entry(tmp_path: Path) -> None:
    meetings = tmp_path / "one" / "two" / "meetings"
    synced: list[Path] = []

    MeetingStore(meetings, directory_sync=synced.append).commit(_audio(tmp_path), _meta())

    assert tmp_path in synced
    assert tmp_path / "one" in synced
    assert tmp_path / "one" / "two" in synced
    assert meetings in synced


@pytest.mark.parametrize(
    "slug",
    [
        "../escaped",
        "/tmp/absolute",
        "nested/slug",
        "nested\\slug",
        ".",
        "..",
        "control\x00slug",
        "méeting",
    ],
)
def test_commit_rejects_unsafe_slug_before_any_store_write(tmp_path: Path, slug: str) -> None:
    meetings = tmp_path / "meetings"
    meta = MeetingMeta(slug=slug, started_at=datetime(2026, 8, 7, tzinfo=UTC))

    with pytest.raises(ValueError, match="canonical ASCII"):
        MeetingStore(meetings).commit(_audio(tmp_path), meta)

    assert not meetings.exists()
    assert not (tmp_path / "escaped").exists()


@pytest.mark.parametrize("existing_content", [None, b"do not replace"])
def test_commit_never_overwrites_existing_empty_or_nonempty_destination(
    tmp_path: Path, existing_content: bytes | None
) -> None:
    meetings = tmp_path / "meetings"
    occupied = meetings / _meta().slug
    occupied.mkdir(parents=True)
    if existing_content is not None:
        (occupied / "sentinel").write_bytes(existing_content)

    files = MeetingStore(meetings).commit(_audio(tmp_path), _meta())

    assert files.meta.slug == f"{_meta().slug}-2"
    assert occupied.exists()
    assert [path.name for path in occupied.iterdir()] == (
        [] if existing_content is None else ["sentinel"]
    )
    if existing_content is not None:
        assert (occupied / "sentinel").read_bytes() == existing_content


def test_commit_collision_suffix_is_race_safe(tmp_path: Path) -> None:
    meetings = tmp_path / "meetings"
    audio = _audio(tmp_path)
    results = []
    barrier = threading.Barrier(2)

    def commit() -> None:
        barrier.wait()
        results.append(MeetingStore(meetings).commit(audio, _meta()))

    threads = [threading.Thread(target=commit) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(result.meta.slug for result in results) == [_meta().slug, f"{_meta().slug}-2"]


@pytest.mark.parametrize("failure", ["materialize", "stub", "file_fsync", "rename"])
def test_pre_publish_failures_leave_no_final_and_keep_recoverable_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    meetings = tmp_path / "meetings"

    def materialize(source: Path, destination: Path) -> None:
        destination.write_bytes(source.read_bytes())
        if failure == "materialize":
            raise OSError("conversion failed")

    if failure == "stub":
        monkeypatch.setattr(
            "meeting_memory.service.meeting_store.render_transcript_stub",
            lambda *_args: (_ for _ in ()).throw(OSError("stub failed")),
        )
    if failure == "file_fsync":
        monkeypatch.setattr(
            "meeting_memory.service.meeting_store.fsync_file",
            lambda _path: (_ for _ in ()).throw(OSError("fsync failed")),
        )

    def publish(source: Path, destination: Path) -> None:
        if failure == "rename":
            raise OSError("rename failed")
        source.rename(destination)

    with pytest.raises(OSError):
        MeetingStore(
            meetings,
            audio_materializer=materialize,
            publisher=publish,
        ).commit(_audio(tmp_path), _meta())

    assert not (meetings / _meta().slug).exists()
    stages = list((meetings / ".meeting-memory-staging").iterdir())
    assert len(stages) == 1
    assert _audio(tmp_path).read_bytes() == b"m4a-audio"


def test_parent_fsync_failure_reports_uncertainty_without_deleting_final(tmp_path: Path) -> None:
    meetings = tmp_path / "meetings"
    calls = 0

    def sync(path: Path) -> None:
        nonlocal calls
        calls += 1
        if path == meetings and (meetings / _meta().slug).exists():
            raise OSError("parent fsync failed")

    with pytest.raises(CommitDurabilityUncertain) as captured:
        MeetingStore(meetings, directory_sync=sync).commit(_audio(tmp_path), _meta())

    files = captured.value.files
    assert calls >= 5
    assert files.audio_path.read_bytes() == b"m4a-audio"
    assert files.transcript_path.is_file()
    assert sorted(path.name for path in files.directory.iterdir()) == [
        "recording.m4a",
        "transcript.md",
    ]


def _audio(tmp_path: Path) -> Path:
    path = tmp_path / "staged.m4a"
    path.write_bytes(b"m4a-audio")
    return path


def _meta() -> MeetingMeta:
    return MeetingMeta(
        slug="2026-08-07_09-30_local-first",
        started_at=datetime(2026, 8, 7, 9, 30, tzinfo=UTC),
        calendar_title="Local First",
        duration_minutes=1,
        speaker_candidates=("Alex",),
    )

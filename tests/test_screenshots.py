"""Tests for per-recording screenshot staging and attachment."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from meeting_memory.service.screenshots import (
    ScreenshotStore,
    ScreenshotUnavailable,
    recording_key_from_slug,
    screenshot_name,
)
from meeting_memory.types.meeting import MeetingRef

STARTED_AT = datetime(2026, 6, 11, 9, 0, tzinfo=UTC)


def test_screenshot_name_encodes_index_and_recording_offset() -> None:
    assert screenshot_name(1, timedelta(seconds=312)) == "screenshot-01-at-05m12s.png"
    assert screenshot_name(12, timedelta(hours=1, seconds=5)) == "screenshot-12-at-1h00m05s.png"
    assert screenshot_name(3, timedelta(seconds=-4)) == "screenshot-03-at-00m00s.png"


def test_recording_key_from_slug_uses_the_start_minute_prefix() -> None:
    assert recording_key_from_slug("2026-06-11_09-00_product-sync") == "2026-06-11_09-00"
    assert recording_key_from_slug("2026-06-11_09-00") == "2026-06-11_09-00"
    assert recording_key_from_slug("product-sync") is None


def test_capture_stages_numbered_screenshots_under_the_recording_key(tmp_path: Path) -> None:
    store = ScreenshotStore(tmp_path / "meetings", capturer=_write_png)

    first = store.capture(STARTED_AT, now=STARTED_AT + timedelta(seconds=65))
    second = store.capture(STARTED_AT, now=STARTED_AT + timedelta(minutes=10))

    pending = tmp_path / "meetings" / ".meeting-memory-staging" / "screenshots" / "2026-06-11_09-00"
    assert (first.index, second.index) == (1, 2)
    assert first.path == pending / "screenshot-01-at-01m05s.png"
    assert second.path == pending / "screenshot-02-at-10m00s.png"
    assert store.pending_count(STARTED_AT) == 2


def test_capture_rejects_an_empty_capture(tmp_path: Path) -> None:
    store = ScreenshotStore(tmp_path / "meetings", capturer=lambda path: path.write_bytes(b""))

    with pytest.raises(ScreenshotUnavailable):
        store.capture(STARTED_AT, now=STARTED_AT)


def test_attach_moves_a_single_screenshot_into_the_meeting_directory(tmp_path: Path) -> None:
    store = ScreenshotStore(tmp_path / "meetings", capturer=_write_png)
    captured = store.capture(STARTED_AT, now=STARTED_AT + timedelta(seconds=5))
    meeting = _publish_meeting(tmp_path / "meetings", "2026-06-11_09-00_product-sync")

    attached = store.attach(meeting)

    assert attached == (meeting.directory / "screenshot-01-at-00m05s.png",)
    assert attached[0].read_bytes() == b"png"
    assert not captured.path.exists()
    assert not captured.path.parent.exists()
    assert not (meeting.directory / "screenshots").exists()


def test_attach_moves_multiple_screenshots_into_a_subfolder(tmp_path: Path) -> None:
    store = ScreenshotStore(tmp_path / "meetings", capturer=_write_png)
    store.capture(STARTED_AT, now=STARTED_AT + timedelta(seconds=5))
    store.capture(STARTED_AT, now=STARTED_AT + timedelta(seconds=9))
    meeting = _publish_meeting(tmp_path / "meetings", "2026-06-11_09-00_product-sync-2")

    attached = store.attach(meeting)

    folder = meeting.directory / "screenshots"
    assert attached == (
        folder / "screenshot-01-at-00m05s.png",
        folder / "screenshot-02-at-00m09s.png",
    )
    assert sorted(path.name for path in folder.iterdir()) == [
        "screenshot-01-at-00m05s.png",
        "screenshot-02-at-00m09s.png",
    ]
    assert store.pending_count(STARTED_AT) == 0


def test_attach_ignores_meetings_without_staged_screenshots(tmp_path: Path) -> None:
    store = ScreenshotStore(tmp_path / "meetings", capturer=_write_png)
    meeting = _publish_meeting(tmp_path / "meetings", "2026-06-11_09-00_product-sync")

    assert store.attach(meeting) == ()
    assert store.attach(MeetingRef("nokey", "Odd", meeting.directory)) == ()


def test_attach_waits_for_a_published_meeting_directory(tmp_path: Path) -> None:
    store = ScreenshotStore(tmp_path / "meetings", capturer=_write_png)
    captured = store.capture(STARTED_AT, now=STARTED_AT)
    missing = MeetingRef(
        "2026-06-11_09-00_product-sync",
        "Product Sync",
        tmp_path / "meetings" / "2026-06-11_09-00_product-sync",
    )
    outside = _publish_meeting(tmp_path / "elsewhere", "2026-06-11_09-00_product-sync")

    assert store.attach(missing) == ()
    assert store.attach(outside) == ()
    assert captured.path.is_file()


def test_attach_keeps_existing_files_and_folders(tmp_path: Path) -> None:
    store = ScreenshotStore(tmp_path / "meetings", capturer=_write_png)
    store.capture(STARTED_AT, now=STARTED_AT + timedelta(seconds=5))
    meeting = _publish_meeting(tmp_path / "meetings", "2026-06-11_09-00_product-sync")
    folder = meeting.directory / "screenshots"
    folder.mkdir()
    (folder / "screenshot-01-at-00m05s.png").write_bytes(b"older")

    attached = store.attach(meeting)

    assert attached == (folder / "screenshot-01-at-00m05s-2.png",)
    assert (folder / "screenshot-01-at-00m05s.png").read_bytes() == b"older"


def _write_png(path: Path) -> None:
    path.write_bytes(b"png")


def _publish_meeting(meetings_dir: Path, slug: str) -> MeetingRef:
    directory = meetings_dir / slug
    directory.mkdir(parents=True)
    (directory / "transcript.md").write_text("---\nschema_version: 2\n---\n")
    (directory / "recording.m4a").write_bytes(b"audio")
    return MeetingRef(slug, "Product Sync", directory)

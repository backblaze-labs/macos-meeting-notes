"""Per-recording screenshot staging and post-commit attachment.

Screenshots taken while a recording is active cannot go into the meeting
directory yet: that directory only appears when the local commit publishes it
with one atomic rename. They are staged under the app-owned staging root on
the ``MEETINGS_DIR`` filesystem, keyed by the recording's start minute (the
same prefix its meeting slug carries), and moved into the published directory
when a committed-meeting event names that slug. One screenshot lands directly
in the meeting directory; two or more land in a ``screenshots/`` subfolder.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from meeting_memory.repo.screen_capture import capture_screen
from meeting_memory.types.meeting import MeetingRef

LOGGER = logging.getLogger(__name__)
SCREENSHOT_SUFFIX = ".png"
SCREENSHOTS_FOLDER = "screenshots"
STAGING_FOLDER = ".meeting-memory-staging"
RECORDING_KEY_FORMAT = "%Y-%m-%d_%H-%M"
_RECORDING_KEY = re.compile(r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}")
Capturer = Callable[[Path], None]


class ScreenshotUnavailable(RuntimeError):
    """The capturer returned without producing a usable image."""


@dataclass(frozen=True)
class CapturedScreenshot:
    path: Path
    index: int


class ScreenshotStore:
    """Stage screenshots per recording and attach them after publication."""

    def __init__(self, meetings_dir: Path, *, capturer: Capturer = capture_screen) -> None:
        self.meetings_dir = meetings_dir.expanduser()
        self.capturer = capturer

    @property
    def pending_root(self) -> Path:
        return self.meetings_dir / STAGING_FOLDER / SCREENSHOTS_FOLDER

    def capture(self, started_at: datetime, *, now: datetime) -> CapturedScreenshot:
        """Capture one screenshot for the recording that began at ``started_at``."""

        pending = self.pending_root / recording_key(started_at)
        pending.mkdir(parents=True, exist_ok=True)
        index = len(_pending_files(pending)) + 1
        destination = pending / screenshot_name(index, now - started_at)
        self.capturer(destination)
        if not destination.is_file() or destination.stat().st_size == 0:
            raise ScreenshotUnavailable(f"no screenshot was written at {destination}")
        return CapturedScreenshot(destination, index)

    def pending_count(self, started_at: datetime) -> int:
        return len(_pending_files(self.pending_root / recording_key(started_at)))

    def attach(self, meeting: MeetingRef) -> tuple[Path, ...]:
        """Move staged screenshots into a published meeting directory."""

        key = recording_key_from_slug(meeting.slug)
        if key is None:
            return ()
        pending = self.pending_root / key
        files = _pending_files(pending)
        if not files or not self._is_meeting_directory(meeting.directory):
            return ()
        existing_folder = meeting.directory / SCREENSHOTS_FOLDER
        if len(files) == 1 and not existing_folder.is_dir():
            target = meeting.directory
        else:
            target = existing_folder
            target.mkdir(exist_ok=True)
        moved: list[Path] = []
        for source in files:
            destination = _unique_destination(target / source.name)
            os.rename(source, destination)
            moved.append(destination)
        try:
            pending.rmdir()
        except OSError:
            LOGGER.debug("Screenshot staging folder %s was not empty", pending)
        return tuple(moved)

    def _is_meeting_directory(self, directory: Path) -> bool:
        if not directory.is_dir() or not (directory / "transcript.md").is_file():
            return False
        return directory.parent.resolve() == self.meetings_dir.resolve()


def recording_key(started_at: datetime) -> str:
    return f"{started_at:{RECORDING_KEY_FORMAT}}"


def recording_key_from_slug(slug: str) -> str | None:
    match = _RECORDING_KEY.match(slug)
    return match.group(0) if match else None


def screenshot_name(index: int, elapsed: timedelta) -> str:
    seconds = max(0, int(elapsed.total_seconds()))
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    offset = f"{hours}h{minutes:02d}m{seconds:02d}s" if hours else f"{minutes:02d}m{seconds:02d}s"
    return f"screenshot-{index:02d}-at-{offset}{SCREENSHOT_SUFFIX}"


def _pending_files(pending: Path) -> list[Path]:
    if not pending.is_dir():
        return []
    return sorted(
        path
        for path in pending.iterdir()
        if path.suffix == SCREENSHOT_SUFFIX and path.is_file() and not path.is_symlink()
    )


def _unique_destination(destination: Path) -> Path:
    candidate = destination
    suffix = 2
    while candidate.exists():
        candidate = destination.with_name(f"{destination.stem}-{suffix}{destination.suffix}")
        suffix += 1
    return candidate

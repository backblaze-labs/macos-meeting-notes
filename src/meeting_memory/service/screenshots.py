"""Per-recording screenshot staging and post-commit attachment.

Screenshots taken while a recording is active cannot go into the meeting
directory yet: that directory only appears when the local commit publishes it
with one atomic rename. They are staged under the app-owned staging root on
the ``MEETINGS_DIR`` filesystem, keyed by the recording's unique capture
session name (the private recovery session directory, which survives title
changes and crash recovery), and moved into the published directory when a
committed-meeting event carries that session name. One screenshot lands
directly in the meeting directory; two or more land in a ``screenshots/``
subfolder.
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
_SESSION_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
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

    def capture(
        self, session_id: str, *, started_at: datetime, now: datetime
    ) -> CapturedScreenshot:
        """Capture one screenshot for the capture session ``session_id``.

        ``started_at`` only names the file by its offset into the recording.
        """

        pending = self.pending_root / validate_session_key(session_id)
        pending.mkdir(parents=True, exist_ok=True)
        index = len(_pending_files(pending)) + 1
        destination = pending / screenshot_name(index, now - started_at)
        self.capturer(destination)
        if not destination.is_file() or destination.stat().st_size == 0:
            raise ScreenshotUnavailable(f"no screenshot was written at {destination}")
        return CapturedScreenshot(destination, index)

    def pending_count(self, session_id: str) -> int:
        return len(_pending_files(self.pending_root / validate_session_key(session_id)))

    def attach(self, meeting: MeetingRef) -> tuple[Path, ...]:
        """Move staged screenshots into a published meeting directory.

        A meeting without a known capture session, or with a session name that
        is not one safe path component, attaches nothing.
        """

        key = session_key(meeting.recording_session)
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


def session_key(session_id: str | None) -> str | None:
    """Return the staging folder name for a capture session, or None if unusable."""

    if not isinstance(session_id, str) or _SESSION_KEY.fullmatch(session_id) is None:
        return None
    return session_id


def validate_session_key(session_id: str) -> str:
    """Reject a capture session name that could escape the staging root."""

    key = session_key(session_id)
    if key is None:
        raise ValueError("capture session name must be one safe path component")
    return key


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

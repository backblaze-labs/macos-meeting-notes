"""Pinned identity and byte checks for one private meeting stage."""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AudioIdentity:
    device: int
    inode: int
    size: int
    sha256: str


@dataclass(frozen=True)
class PublishedStageIdentity:
    directory_device: int
    directory_inode: int
    audio: AudioIdentity


class PinnedMeetingStage:
    """Keep one stage and its accepted audio pinned across path-based validation."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.directory_fd = os.open(
            path,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
        )
        directory = os.fstat(self.directory_fd)
        self.directory_identity = (directory.st_dev, directory.st_ino)
        self.audio_fd = -1
        self.audio_identity: AudioIdentity | None = None

    def pin_audio(self) -> AudioIdentity:
        if self.audio_fd >= 0:
            raise RuntimeError("meeting stage audio is already pinned")
        self.audio_fd = os.open(
            "recording.m4a",
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=self.directory_fd,
        )
        info = os.fstat(self.audio_fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size <= 0:
            raise ValueError("audio materializer produced no regular recording")
        self.audio_identity = AudioIdentity(
            info.st_dev,
            info.st_ino,
            info.st_size,
            _sha256(self.audio_fd, info.st_size),
        )
        return self.audio_identity

    def validate_visible(self) -> None:
        """Require the lexical stage and child to still name the pinned objects."""

        identity = self._require_audio_identity()
        visible_stage = self.path.stat(follow_symlinks=False)
        if (
            not stat.S_ISDIR(visible_stage.st_mode)
            or (visible_stage.st_dev, visible_stage.st_ino) != self.directory_identity
        ):
            raise ValueError("meeting stage directory changed before publication")
        self._validate_audio_at(self.directory_fd, identity)

    def validate_published(self, destination: Path) -> None:
        """Require the published directory/audio to be the exact pinned stage objects."""

        identity = self._require_audio_identity()
        directory_fd = os.open(
            destination,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
        )
        try:
            directory = os.fstat(directory_fd)
            if (directory.st_dev, directory.st_ino) != self.directory_identity:
                raise ValueError("published meeting directory is not the pinned stage")
            self._validate_audio_at(directory_fd, identity)
        finally:
            os.close(directory_fd)

    @contextmanager
    def validation_snapshot(self) -> Iterator[Path]:
        """Expose exact accepted bytes through an unlinked read-only descriptor path."""

        identity = self._require_audio_identity()
        writer_fd, raw_path = tempfile.mkstemp(
            prefix="meeting-memory-validation.",
            dir=self.path.parent,
        )
        snapshot = Path(raw_path)
        created = os.fstat(writer_fd)
        snapshot_identity = (created.st_dev, created.st_ino)
        reader_fd = -1
        try:
            digest = hashlib.sha256()
            with os.fdopen(writer_fd, "wb") as writer:
                for offset in range(0, identity.size, 1024 * 1024):
                    chunk = os.pread(
                        self.audio_fd,
                        min(1024 * 1024, identity.size - offset),
                        offset,
                    )
                    if not chunk:
                        raise ValueError("meeting audio changed during validation snapshot")
                    writer.write(chunk)
                    digest.update(chunk)
                writer.flush()
                os.fsync(writer.fileno())
            if digest.hexdigest() != identity.sha256:
                raise ValueError("validation snapshot does not match materialized audio")
            os.chmod(snapshot, 0o400, follow_symlinks=False)
            reader_fd = os.open(snapshot, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            opened = os.fstat(reader_fd)
            visible = snapshot.stat(follow_symlinks=False)
            if (opened.st_dev, opened.st_ino) != (visible.st_dev, visible.st_ino):
                raise ValueError("validation snapshot changed before unlink")
            snapshot.unlink()
            yield Path(f"/dev/fd/{reader_fd}")
        finally:
            if reader_fd >= 0:
                os.close(reader_fd)
            _unlink_same_snapshot(snapshot, snapshot_identity)

    def fsync_audio(self) -> None:
        self._require_audio_identity()
        os.fsync(self.audio_fd)

    def fsync_directory(self) -> None:
        os.fsync(self.directory_fd)

    def publication_identity(self) -> PublishedStageIdentity:
        audio = self._require_audio_identity()
        return PublishedStageIdentity(*self.directory_identity, audio)

    def close(self) -> None:
        if self.audio_fd >= 0:
            os.close(self.audio_fd)
            self.audio_fd = -1
        os.close(self.directory_fd)

    def __enter__(self) -> PinnedMeetingStage:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _require_audio_identity(self) -> AudioIdentity:
        if self.audio_fd < 0 or self.audio_identity is None:
            raise RuntimeError("meeting stage audio is not pinned")
        opened = os.fstat(self.audio_fd)
        identity = self.audio_identity
        if (
            (opened.st_dev, opened.st_ino, opened.st_size)
            != (identity.device, identity.inode, identity.size)
            or _sha256(self.audio_fd, opened.st_size) != identity.sha256
        ):
            raise ValueError("pinned meeting audio changed before publication")
        return identity

    @staticmethod
    def _validate_audio_at(directory_fd: int, identity: AudioIdentity) -> None:
        descriptor = os.open(
            "recording.m4a",
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=directory_fd,
        )
        try:
            opened = os.fstat(descriptor)
            visible = os.stat(
                "recording.m4a",
                dir_fd=directory_fd,
                follow_symlinks=False,
            )
            expected = (identity.device, identity.inode, identity.size)
            if (
                not stat.S_ISREG(opened.st_mode)
                or expected != (opened.st_dev, opened.st_ino, opened.st_size)
                or expected != (visible.st_dev, visible.st_ino, visible.st_size)
                or _sha256(descriptor, opened.st_size) != identity.sha256
            ):
                raise ValueError("meeting audio changed before publication")
        finally:
            os.close(descriptor)


def _sha256(descriptor: int, size: int) -> str:
    digest = hashlib.sha256()
    for offset in range(0, size, 1024 * 1024):
        chunk = os.pread(descriptor, min(1024 * 1024, size - offset), offset)
        if not chunk:
            raise ValueError("meeting audio became unreadable")
        digest.update(chunk)
    return digest.hexdigest()


def _unlink_same_snapshot(path: Path, expected: tuple[int, int]) -> None:
    try:
        info = path.stat(follow_symlinks=False)
    except FileNotFoundError:
        return
    if stat.S_ISREG(info.st_mode) and (info.st_dev, info.st_ino) == expected:
        path.unlink()

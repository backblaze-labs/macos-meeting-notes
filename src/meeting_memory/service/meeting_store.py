"""Inactive local-first store for atomic meeting-directory commits."""

from __future__ import annotations

import os
import stat
import tempfile
from collections.abc import Callable
from pathlib import Path

from meeting_memory.service.atomic_io import (
    copy_audio,
    fsync_directory,
    fsync_file,
    rename_directory_no_replace,
    write_text_durable,
)
from meeting_memory.service.markdown import render_transcript_stub
from meeting_memory.service.meeting_locks import meeting_lock
from meeting_memory.types.meeting import (
    MeetingFiles,
    MeetingMeta,
    PostCommitPolicy,
    validate_meeting_slug,
)

AudioMaterializer = Callable[[Path, Path], None]
PinnedAudioMaterializer = Callable[[int, Path], None]
PinnedSourceValidator = Callable[[int], None]
MaterializedAudioValidator = Callable[[Path], None]
Publisher = Callable[[Path, Path], None]
DirectorySync = Callable[[Path], None]


class CommitDurabilityUncertain(RuntimeError):
    """Publication succeeded, but flushing the parent directory failed."""

    def __init__(self, files: MeetingFiles, cause: OSError) -> None:
        self.files = files
        self.cause = cause
        super().__init__(
            f"meeting committed at {files.directory}; durability flush failed: {cause}"
        )

    def __str__(self) -> str:
        return str(self.args[0])


class MeetingStore:
    """Build two local artifacts, then publish their directory in one rename."""

    def __init__(
        self,
        meetings_dir: Path,
        *,
        audio_materializer: AudioMaterializer = copy_audio,
        publisher: Publisher = rename_directory_no_replace,
        directory_sync: DirectorySync = fsync_directory,
    ) -> None:
        self.meetings_dir = meetings_dir.expanduser()
        self.audio_materializer = audio_materializer
        self.publisher = publisher
        self.directory_sync = directory_sync

    def commit(
        self,
        staged_audio: Path,
        meta: MeetingMeta,
        policy: PostCommitPolicy = PostCommitPolicy(),
    ) -> MeetingFiles:
        """Commit audio and a schema-v2 stub without invoking a provider."""

        self._validate_slug(meta.slug)
        self._validate_source(staged_audio)
        return self._commit(staged_audio, meta, policy, self.audio_materializer)

    def commit_pinned_audio(
        self,
        source_fd: int,
        meta: MeetingMeta,
        policy: PostCommitPolicy = PostCommitPolicy(),
        *,
        materializer: PinnedAudioMaterializer,
        validate_source: PinnedSourceValidator,
        validate_materialized: MaterializedAudioValidator,
    ) -> MeetingFiles:
        """Commit bytes from one caller-pinned non-empty regular descriptor."""

        self._validate_slug(meta.slug)
        info = os.fstat(source_fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size == 0:
            raise ValueError("pinned audio must be a non-empty regular file")

        def materialize(_source: Path, destination: Path) -> None:
            materializer(source_fd, destination)
            validate_materialized(destination)
            validate_source(source_fd)

        return self._commit(Path("pinned-audio"), meta, policy, materialize)

    def _commit(
        self,
        staged_audio: Path,
        meta: MeetingMeta,
        policy: PostCommitPolicy,
        materializer: AudioMaterializer,
    ) -> MeetingFiles:
        self._ensure_directory(self.meetings_dir)
        staging_root = self.meetings_dir / ".meeting-memory-staging"
        self._ensure_directory(staging_root)

        with meeting_lock(self.meetings_dir, meta.slug):
            raw_stage = tempfile.mkdtemp(prefix=f"{meta.slug}.", dir=staging_root)
            stage = Path(raw_stage)
            self.directory_sync(staging_root)
            audio_path = stage / "recording.m4a"
            materializer(staged_audio, audio_path)
            self._validate_materialized_audio(audio_path)
            fsync_file(audio_path)

            suffix = 1
            while True:
                slug = meta.slug if suffix == 1 else f"{meta.slug}-{suffix}"
                final_meta = meta.with_slug(slug)
                transcript_path = stage / "transcript.md"
                self._write_stub(transcript_path, final_meta, policy)
                self.directory_sync(stage)
                destination = self._destination(slug)
                if final_meta.slug != destination.name:
                    raise ValueError("meeting id must match its directory name")
                try:
                    self.publisher(stage, destination)
                except FileExistsError:
                    suffix += 1
                    continue

                files = MeetingFiles(
                    meta=final_meta,
                    directory=destination,
                    audio_path=destination / "recording.m4a",
                    markdown_path=destination / "transcript.md",
                    notes_path=destination / "notes.md",
                )
                try:
                    self.directory_sync(staging_root)
                    self.directory_sync(self.meetings_dir)
                except OSError as exc:
                    raise CommitDurabilityUncertain(files, exc) from exc
                return files

    @staticmethod
    def _validate_slug(slug: str) -> None:
        validate_meeting_slug(slug)

    @staticmethod
    def _validate_source(staged_audio: Path) -> None:
        if not staged_audio.is_file() or staged_audio.stat().st_size == 0:
            raise ValueError("staged audio must be a non-empty, readable file")
        with staged_audio.open("rb") as stream:
            stream.read(1)

    @staticmethod
    def _validate_materialized_audio(audio_path: Path) -> None:
        if not audio_path.is_file() or audio_path.stat().st_size == 0:
            raise ValueError("audio materializer produced no recording")
        with audio_path.open("rb") as stream:
            stream.read(1)

    @staticmethod
    def _write_stub(
        transcript_path: Path,
        meta: MeetingMeta,
        policy: PostCommitPolicy,
    ) -> None:
        text = render_transcript_stub(meta, policy)
        if transcript_path.exists():
            write_text_durable(transcript_path, text)
        else:
            write_text_durable(transcript_path, text, exclusive=True)

    def _ensure_directory(self, path: Path) -> None:
        missing: list[Path] = []
        cursor = path
        while not cursor.exists():
            missing.append(cursor)
            cursor = cursor.parent
        path.mkdir(parents=True, exist_ok=True)
        for created in reversed(missing):
            self.directory_sync(created.parent)

    def _destination(self, slug: str) -> Path:
        destination = self.meetings_dir / slug
        if destination.name != slug or destination.parent.resolve() != self.meetings_dir.resolve():
            raise ValueError("meeting destination escaped MEETINGS_DIR")
        return destination

"""Local-first store for atomic meeting-directory commits."""

from __future__ import annotations

import os
import stat
import tempfile
from collections.abc import Callable
from pathlib import Path

from meeting_memory.service.atomic_io import (
    atomic_replace_text_at,
    copy_audio,
    fsync_directory,
    rename_directory_no_replace,
)
from meeting_memory.service.markdown import render_transcript_stub
from meeting_memory.service.meeting_locks import meeting_lock
from meeting_memory.service.stage_integrity import (
    PinnedMeetingStage,
    PublishedStageIdentity,
)
from meeting_memory.types.meeting import (
    MeetingDirectoryIdentity,
    MeetingFiles,
    MeetingMeta,
    PostCommitPolicy,
    validate_meeting_slug,
)

AudioMaterializer = Callable[[Path, Path], None]
PinnedAudioMaterializer = Callable[[int, Path], None]
PinnedSourceValidator = Callable[[int], None]
MaterializedAudioValidator = Callable[[Path], None]
PublicationPreparer = Callable[[Path, MeetingMeta], None]
PublicationObserver = Callable[[MeetingFiles, PublishedStageIdentity], None]
Publisher = Callable[[Path, Path], None]
DirectorySync = Callable[[Path], None]


class MeetingStageCleanupUncertain(RuntimeError):
    """A failed pre-publication stage could not be removed safely."""

    def __init__(self, stage: Path, primary: BaseException, cleanup: BaseException) -> None:
        self.stage = stage
        self.primary = primary
        self.cleanup = cleanup
        super().__init__(f"failed meeting stage cleanup at {stage}: {cleanup}")


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


class MeetingPublicationIntegrityError(RuntimeError):
    """A publisher exposed bytes other than the pinned validated stage."""

    def __init__(self, destination: Path, cause: BaseException) -> None:
        self.destination = destination
        self.cause = cause
        super().__init__(f"published meeting failed identity validation: {destination}")


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
        prepare_publication: PublicationPreparer | None = None,
        observe_publication: PublicationObserver | None = None,
    ) -> MeetingFiles:
        """Commit bytes from one caller-pinned non-empty regular descriptor."""

        self._validate_slug(meta.slug)
        info = os.fstat(source_fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size == 0:
            raise ValueError("pinned audio must be a non-empty regular file")

        def materialize(_source: Path, destination: Path) -> None:
            materializer(source_fd, destination)
            validate_source(source_fd)

        return self._commit(
            Path("pinned-audio"),
            meta,
            policy,
            materialize,
            prepare_publication,
            validate_materialized,
            observe_publication,
        )

    def _commit(
        self,
        staged_audio: Path,
        meta: MeetingMeta,
        policy: PostCommitPolicy,
        materializer: AudioMaterializer,
        prepare_publication: PublicationPreparer | None = None,
        validate_materialized: MaterializedAudioValidator | None = None,
        observe_publication: PublicationObserver | None = None,
    ) -> MeetingFiles:
        self._ensure_directory(self.meetings_dir)
        staging_root = self.meetings_dir / ".meeting-memory-staging"
        self._ensure_directory(staging_root)

        with meeting_lock(self.meetings_dir, meta.slug):
            raw_stage = tempfile.mkdtemp(prefix=f"{meta.slug}.", dir=staging_root)
            stage = Path(raw_stage)
            stage_info = stage.stat(follow_symlinks=False)
            published = False
            try:
                with PinnedMeetingStage(stage) as pinned:
                    if pinned.directory_identity != (stage_info.st_dev, stage_info.st_ino):
                        raise ValueError("meeting stage changed before it was pinned")
                    self.directory_sync(staging_root)
                    audio_path = stage / "recording.m4a"
                    materializer(staged_audio, audio_path)
                    pinned.pin_audio()
                    if validate_materialized is not None:
                        with pinned.validation_snapshot() as validation_path:
                            validate_materialized(validation_path)
                    pinned.validate_visible()
                    pinned.fsync_audio()

                    suffix = 1
                    while True:
                        slug = meta.slug if suffix == 1 else f"{meta.slug}-{suffix}"
                        final_meta = meta.with_slug(slug)
                        self._write_stub(pinned.directory_fd, final_meta, policy)
                        if prepare_publication is not None:
                            prepare_publication(stage, final_meta)
                        pinned.validate_visible()
                        pinned.fsync_directory()
                        destination = self._destination(slug)
                        if final_meta.slug != destination.name:
                            raise ValueError("meeting id must match its directory name")
                        pinned.validate_visible()
                        try:
                            self.publisher(stage, destination)
                        except FileExistsError:
                            suffix += 1
                            continue
                        published = True
                        try:
                            pinned.validate_published(destination)
                        except (OSError, ValueError) as exc:
                            raise MeetingPublicationIntegrityError(
                                destination,
                                exc,
                            ) from exc
                        published_identity = pinned.publication_identity()
                        files = MeetingFiles(
                            meta=final_meta,
                            directory=destination,
                            audio_path=destination / "recording.m4a",
                            markdown_path=destination / "transcript.md",
                            notes_path=destination / "notes.md",
                            directory_identity=MeetingDirectoryIdentity(
                                published_identity.directory_device,
                                published_identity.directory_inode,
                            ),
                        )
                        if observe_publication is not None:
                            observe_publication(files, published_identity)
                        try:
                            self.directory_sync(staging_root)
                            self.directory_sync(self.meetings_dir)
                        except OSError as exc:
                            raise CommitDurabilityUncertain(files, exc) from exc
                        return files
            except BaseException as primary:
                if not published:
                    try:
                        _remove_stage(staging_root, stage.name, stage_info)
                    except BaseException as cleanup:
                        raise MeetingStageCleanupUncertain(
                            stage,
                            primary,
                            cleanup,
                        ) from primary
                raise

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
    def _write_stub(
        directory_fd: int,
        meta: MeetingMeta,
        policy: PostCommitPolicy,
    ) -> None:
        text = render_transcript_stub(meta, policy)
        atomic_replace_text_at(directory_fd, "transcript.md", text)

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


def _remove_stage(staging_root: Path, name: str, expected: os.stat_result) -> None:
    root_fd = os.open(staging_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    stage_fd = -1
    try:
        stage_fd = os.open(
            name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=root_fd,
        )
        current = os.fstat(stage_fd)
        if (current.st_dev, current.st_ino) != (expected.st_dev, expected.st_ino):
            raise ValueError("meeting stage changed before cleanup")
        for child in os.listdir(stage_fd):
            info = os.stat(child, dir_fd=stage_fd, follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("meeting stage contains a non-regular artifact")
            os.unlink(child, dir_fd=stage_fd)
        os.fsync(stage_fd)
        os.rmdir(name, dir_fd=root_fd)
        os.fsync(root_fd)
    finally:
        if stage_fd >= 0:
            os.close(stage_fd)
        os.close(root_fd)

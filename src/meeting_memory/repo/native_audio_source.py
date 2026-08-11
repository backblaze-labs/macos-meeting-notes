"""Pinned FFmpeg source acquisition for the build-only AAC encoder."""

from __future__ import annotations

import hashlib
import io
import os
import stat
import tarfile
import tempfile
import urllib.request
from pathlib import Path

FFMPEG_VERSION = "8.1.2"
FFMPEG_SOURCE_ARCHIVE_NAME = f"ffmpeg-{FFMPEG_VERSION}.tar.xz"
FFMPEG_ARCHIVE_URL = f"https://ffmpeg.org/releases/{FFMPEG_SOURCE_ARCHIVE_NAME}"
FFMPEG_ARCHIVE_SHA256 = "464beb5e7bf0c311e68b45ae2f04e9cc2af88851abb4082231742a74d97b524c"
VENDORED_SOURCE_DIRECTORY = Path("packaging/vendor")
MAX_ARCHIVE_BYTES = 32 * 1024 * 1024


class NativeAudioSourceError(RuntimeError):
    """Raised when pinned FFmpeg source is unavailable or invalid."""


def verified_source_archive(
    project_dir: Path,
    archive_path: Path | None = None,
) -> bytes:
    """Return one stable source snapshot that matches the pinned release hash."""

    if archive_path is not None:
        return read_verified_source_archive(archive_path)
    vendored = project_dir / VENDORED_SOURCE_DIRECTORY / FFMPEG_SOURCE_ARCHIVE_NAME
    if vendored.exists() or vendored.is_symlink():
        return read_verified_source_archive(vendored)
    return read_verified_source_archive(_cached_archive(project_dir))


def read_verified_source_archive(path: Path) -> bytes:
    """Read one stable regular source archive and enforce the release checksum."""

    return _read_verified_archive(path)


def extract_source(archive: bytes, destination: Path) -> None:
    """Extract a verified source snapshot with tar traversal/link defenses."""

    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:xz") as source:
            members = source.getmembers()
            if any(member.issym() or member.islnk() for member in members):
                raise NativeAudioSourceError("FFmpeg source archive contains links.")
            source.extractall(destination, members=members, filter="data")
    except NativeAudioSourceError:
        raise
    except (OSError, tarfile.TarError):
        raise NativeAudioSourceError("FFmpeg source archive could not be extracted.") from None


def write_verified_source_archive(archive: bytes, destination: Path) -> None:
    """Atomically retain the exact source snapshot shipped with the executable."""

    if hashlib.sha256(archive).hexdigest() != FFMPEG_ARCHIVE_SHA256:
        raise NativeAudioSourceError("FFmpeg source archive checksum does not match.")
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", dir=destination.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(archive)
                output.flush()
                os.fsync(output.fileno())
            temporary.chmod(0o644)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
    except OSError:
        raise NativeAudioSourceError("FFmpeg source archive could not be retained.") from None


def _cached_archive(project_dir: Path) -> Path:
    cache = project_dir / "build" / "dependencies" / FFMPEG_SOURCE_ARCHIVE_NAME
    if cache.is_file():
        return cache
    cache.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache.with_suffix(".download")
    temporary.unlink(missing_ok=True)
    try:
        with urllib.request.urlopen(FFMPEG_ARCHIVE_URL, timeout=120) as response:
            with temporary.open("xb") as destination:
                size = 0
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_ARCHIVE_BYTES:
                        raise NativeAudioSourceError("FFmpeg source archive is oversized.")
                    destination.write(chunk)
                destination.flush()
                os.fsync(destination.fileno())
        read_verified_source_archive(temporary)
        os.replace(temporary, cache)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise NativeAudioSourceError("Could not fetch verified FFmpeg source.") from None
    return cache


def _read_verified_archive(path: Path) -> bytes:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK | os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_ARCHIVE_BYTES:
                raise NativeAudioSourceError("FFmpeg source archive is unavailable.")
            chunks: list[bytes] = []
            size = 0
            while chunk := os.read(descriptor, 1024 * 1024):
                size += len(chunk)
                if size > MAX_ARCHIVE_BYTES:
                    raise NativeAudioSourceError("FFmpeg source archive is unavailable.")
                chunks.append(chunk)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
    except NativeAudioSourceError:
        raise
    except OSError:
        raise NativeAudioSourceError("FFmpeg source archive is unavailable.") from None
    if (
        before.st_dev != after.st_dev
        or before.st_ino != after.st_ino
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or before.st_ctime_ns != after.st_ctime_ns
        or size != before.st_size
    ):
        raise NativeAudioSourceError("FFmpeg source archive changed while reading.")
    payload = b"".join(chunks)
    if hashlib.sha256(payload).hexdigest() != FFMPEG_ARCHIVE_SHA256:
        raise NativeAudioSourceError("FFmpeg source archive checksum does not match.")
    return payload

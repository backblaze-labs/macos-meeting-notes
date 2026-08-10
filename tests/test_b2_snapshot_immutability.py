"""Anonymous-handle immutability tests for Backup snapshot upload."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from meeting_memory.repo.b2_client import B2S3Client
from meeting_memory.service.backup_revision import capture_backup_snapshot
from meeting_memory.types.artifacts import (
    BackupUploadCancellation,
    BackupUploadDisposition,
)

SLUG = "2026-08-10_10-00_immutable"
TRANSCRIPT = b"""---
schema_version: 2
created_by: meeting-memory
id: 2026-08-10_10-00_immutable
backup_status: pending
---
# Transcript
"""


def test_path_mutation_during_upload_cannot_change_verified_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = _snapshot(tmp_path)
    provider = MutatingProvider(snapshot.audio_path, snapshot.transcript_path)
    monkeypatch.setattr(B2S3Client, "_client", lambda _self: provider)

    result = _adapter().upload_backup_snapshot(
        snapshot.upload_request(),
        cancellation=BackupUploadCancellation(),
    )

    assert result.disposition is BackupUploadDisposition.COMPLETE
    assert result.revision == snapshot.revision
    assert provider.uploads == [
        (b"original audio", f"meetings/{SLUG}/recording.m4a"),
        (TRANSCRIPT, f"meetings/{SLUG}/transcript.md"),
    ]
    assert all(stream.closed for stream in provider.streams)
    assert all(isinstance(stream.name, int) for stream in provider.streams)
    snapshot.cleanup()


def test_retry_rewinds_same_anonymous_audio_handle_after_path_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = _snapshot(tmp_path)
    provider = RetryMutatingProvider(snapshot.audio_path)
    monkeypatch.setattr(B2S3Client, "_client", lambda _self: provider)

    result = _adapter(retry_delays=(0.0,), sleeper=lambda _delay: None).upload_backup_snapshot(
        snapshot.upload_request(),
        cancellation=BackupUploadCancellation(),
    )

    assert result.disposition is BackupUploadDisposition.COMPLETE
    assert provider.audio_attempts == [b"original audio", b"original audio"]
    assert len(set(provider.audio_stream_ids)) == 1
    snapshot.cleanup()


def test_provider_cannot_write_or_truncate_read_only_retry_streams(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = _snapshot(tmp_path)
    provider = ReadOnlyAttackProvider()
    monkeypatch.setattr(B2S3Client, "_client", lambda _self: provider)

    result = _adapter(retry_delays=(0.0,), sleeper=lambda _delay: None).upload_backup_snapshot(
        snapshot.upload_request(),
        cancellation=BackupUploadCancellation(),
    )

    assert result.disposition is BackupUploadDisposition.COMPLETE
    assert result.revision == snapshot.revision
    assert provider.audio_attempts == [b"original audio", b"original audio"]
    assert provider.transcript == TRANSCRIPT
    assert len(provider.rejections) == 6
    assert all(isinstance(error, io.UnsupportedOperation) for error in provider.rejections)
    snapshot.cleanup()


class MutatingProvider:
    def __init__(self, audio_path: Path, transcript_path: Path) -> None:
        self.audio_path = audio_path
        self.transcript_path = transcript_path
        self.uploads: list[tuple[bytes, str]] = []
        self.streams: list[object] = []

    def upload_fileobj(self, stream, _bucket: str, key: str) -> None:
        self.streams.append(stream)
        self.uploads.append((stream.read(), key))
        if len(self.uploads) == 1:
            self.audio_path.write_bytes(b"mutated audio")
            self.transcript_path.write_bytes(b"mutated transcript")


class RetryMutatingProvider:
    def __init__(self, audio_path: Path) -> None:
        self.audio_path = audio_path
        self.audio_attempts: list[bytes] = []
        self.audio_stream_ids: list[int] = []

    def upload_fileobj(self, stream, _bucket: str, key: str) -> None:
        body = stream.read()
        if key.endswith("recording.m4a"):
            self.audio_stream_ids.append(id(stream))
            self.audio_attempts.append(body)
            if len(self.audio_attempts) == 1:
                self.audio_path.write_bytes(b"mutated between retries")
                raise RuntimeError("retry me")


class ReadOnlyAttackProvider:
    def __init__(self) -> None:
        self.audio_attempts: list[bytes] = []
        self.transcript: bytes | None = None
        self.rejections: list[Exception] = []

    def upload_fileobj(self, stream, _bucket: str, key: str) -> None:
        for mutation in (
            lambda: stream.write(b"provider mutation"),
            lambda: stream.truncate(0),
        ):
            try:
                mutation()
            except Exception as exc:
                self.rejections.append(exc)
            else:
                raise AssertionError("provider mutated a read-only backup stream")
        content = stream.read()
        if key.endswith("recording.m4a"):
            self.audio_attempts.append(content)
            if len(self.audio_attempts) == 1:
                raise RuntimeError("retry after rejected mutation")
        else:
            self.transcript = content


def _adapter(**kwargs) -> B2S3Client:
    return B2S3Client("id", "secret", "endpoint", "region", "bucket", **kwargs)


def _snapshot(tmp_path: Path):
    meeting = tmp_path / SLUG
    meeting.mkdir()
    (meeting / "recording.m4a").write_bytes(b"original audio")
    (meeting / "transcript.md").write_bytes(TRANSCRIPT)
    return capture_backup_snapshot(meeting, tmp_path / "snapshots")

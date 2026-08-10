"""Cancellable, verified per-object Backup upload seam tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from meeting_memory.repo.b2_client import B2S3Client
from meeting_memory.service.backup_revision import BackupSnapshot, capture_backup_snapshot
from meeting_memory.types.artifacts import (
    BackupSnapshotUpload,
    BackupSnapshotUploadResult,
    BackupUploadCancellation,
    BackupUploadDisposition,
)

TRANSCRIPT = b"""---
schema_version: 2
created_by: meeting-memory
id: 2026-08-10_10-00_backup
backup_status: pending
---
# Transcript
"""
SLUG = "2026-08-10_10-00_backup"


def test_cancelled_at_entry_does_no_snapshot_or_client_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = _snapshot(tmp_path)
    token = BackupUploadCancellation()
    token.cancel()

    def explode(_self):
        raise AssertionError("cancelled upload constructed a provider client")

    monkeypatch.setattr(B2S3Client, "_client", explode)
    result = _adapter().upload_backup_snapshot(snapshot.upload_request(), cancellation=token)
    assert result.disposition is BackupUploadDisposition.CANCELLED
    snapshot.cleanup()


def test_complete_upload_uses_exact_snapshot_objects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = _snapshot(tmp_path)
    provider = FakeStreamClient()
    monkeypatch.setattr(B2S3Client, "_client", lambda _self: provider)

    result = _adapter().upload_backup_snapshot(
        snapshot.upload_request(),
        cancellation=BackupUploadCancellation(),
    )

    assert result.disposition is BackupUploadDisposition.COMPLETE
    assert provider.uploads == [
        (b"audio", "meetings/2026-08-10_10-00_backup/recording.m4a"),
        (TRANSCRIPT, "meetings/2026-08-10_10-00_backup/transcript.md"),
    ]
    snapshot.cleanup()


def test_old_worker_stays_cancelled_after_audio_even_if_new_token_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = _snapshot(tmp_path)
    old_token = BackupUploadCancellation()
    provider = FakeStreamClient(after_upload=old_token.cancel)
    monkeypatch.setattr(B2S3Client, "_client", lambda _self: provider)

    result = _adapter().upload_backup_snapshot(
        snapshot.upload_request(), cancellation=old_token
    )
    new_enabled_worker = BackupUploadCancellation()

    assert not new_enabled_worker.cancelled
    assert result.disposition is BackupUploadDisposition.PARTIAL
    assert result.pending_ready
    assert [key for _body, key in provider.uploads] == [
        "meetings/2026-08-10_10-00_backup/recording.m4a"
    ]
    snapshot.cleanup()


def test_cancellation_between_internal_retries_stops_without_transcript(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = _snapshot(tmp_path)
    token = BackupUploadCancellation()
    provider = FakeStreamClient(fail_once=True, after_failure=token.cancel)
    monkeypatch.setattr(B2S3Client, "_client", lambda _self: provider)
    sleeps: list[float] = []

    result = _adapter(retry_delays=(1.0,), sleeper=sleeps.append).upload_backup_snapshot(
        snapshot.upload_request(), cancellation=token
    )

    assert result.disposition is BackupUploadDisposition.CANCELLED
    assert provider.attempted_keys == [f"meetings/{SLUG}/recording.m4a"]
    assert sleeps == []
    snapshot.cleanup()


def test_terminal_audio_failure_never_attempts_transcript(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = _snapshot(tmp_path)
    provider = FakeStreamClient(always_fail=True)
    monkeypatch.setattr(B2S3Client, "_client", lambda _self: provider)

    with pytest.raises(RuntimeError, match="provider failure"):
        _adapter(retry_delays=()).upload_backup_snapshot(
            snapshot.upload_request(), cancellation=BackupUploadCancellation()
        )

    assert provider.attempted_keys == [f"meetings/{SLUG}/recording.m4a"]
    snapshot.cleanup()


@pytest.mark.parametrize("mutation", ["bytes", "symlink", "wrong-revision"])
def test_snapshot_tampering_fails_before_provider_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    snapshot = _snapshot(tmp_path)
    request = snapshot.upload_request()
    if mutation == "bytes":
        snapshot.transcript_path.write_bytes(TRANSCRIPT + b"changed")
    elif mutation == "symlink":
        secret = tmp_path / "secret"
        secret.write_bytes(b"private")
        snapshot.transcript_path.unlink()
        snapshot.transcript_path.symlink_to(secret)
    else:
        request = BackupSnapshotUpload(
            SLUG,
            "0" * 64,
            request.directory,
            request.directory_device,
            request.directory_inode,
        )
    monkeypatch.setattr(
        B2S3Client,
        "_client",
        lambda _self: (_ for _ in ()).throw(AssertionError("provider called")),
    )

    with pytest.raises((OSError, ValueError)):
        _adapter().upload_backup_snapshot(request, cancellation=BackupUploadCancellation())


def test_snapshot_identity_cannot_be_retargeted_to_another_slug(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = _snapshot(tmp_path)
    request = snapshot.upload_request()
    wrong_slug = "2026-08-10_10-01_other"
    forged = BackupSnapshotUpload(
        wrong_slug,
        request.revision,
        request.directory,
        request.directory_device,
        request.directory_inode,
    )
    monkeypatch.setattr(
        B2S3Client,
        "_client",
        lambda _self: (_ for _ in ()).throw(AssertionError("provider called")),
    )

    with pytest.raises(ValueError, match="identity does not match"):
        _adapter().upload_backup_snapshot(
            forged,
            cancellation=BackupUploadCancellation(),
        )


def test_boundary_request_derives_both_paths_from_one_directory(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    request = snapshot.upload_request()
    assert request.audio_path == snapshot.directory / "recording.m4a"
    assert request.transcript_path == snapshot.directory / "transcript.md"
    with pytest.raises(TypeError, match="must be BackupUploadDisposition"):
        BackupSnapshotUploadResult("complete", SLUG, snapshot.revision)  # type: ignore[arg-type]
    snapshot.cleanup()


def test_snapshot_cleanup_is_identity_safe_idempotent_and_preserves_primary_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = _snapshot(tmp_path)
    original = snapshot.directory.with_name("original")
    snapshot.directory.rename(original)
    snapshot.directory.mkdir(mode=0o700)
    (snapshot.directory / "replacement").write_bytes(b"keep")
    with pytest.raises(ValueError, match="replaced"):
        snapshot.cleanup()
    assert (snapshot.directory / "replacement").read_bytes() == b"keep"

    clean = _snapshot(tmp_path / "clean")
    clean.cleanup()
    clean.cleanup()
    monkeypatch.setattr(BackupSnapshot, "cleanup", lambda _self: (_ for _ in ()).throw(OSError()))
    with pytest.raises(RuntimeError, match="primary"):
        with clean:
            raise RuntimeError("primary")


class FakeStreamClient:
    def __init__(
        self,
        *,
        fail_once: bool = False,
        always_fail: bool = False,
        after_upload=None,
        after_failure=None,
    ) -> None:
        self.fail_once = fail_once
        self.always_fail = always_fail
        self.after_upload = after_upload
        self.after_failure = after_failure
        self.attempted_keys: list[str] = []
        self.uploads: list[tuple[bytes, str]] = []

    def upload_fileobj(self, stream, _bucket: str, key: str) -> None:
        self.attempted_keys.append(key)
        if self.always_fail or self.fail_once:
            self.fail_once = False
            if self.after_failure:
                self.after_failure()
            raise RuntimeError("provider failure")
        self.uploads.append((stream.read(), key))
        if self.after_upload:
            self.after_upload()


def _adapter(**kwargs) -> B2S3Client:
    return B2S3Client("id", "secret", "endpoint", "region", "bucket", **kwargs)


def _snapshot(tmp_path: Path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    meeting = tmp_path / SLUG
    meeting.mkdir()
    audio = meeting / "recording.m4a"
    transcript = meeting / "transcript.md"
    audio.write_bytes(b"audio")
    transcript.write_bytes(TRANSCRIPT)
    return capture_backup_snapshot(meeting, tmp_path / "snapshots")

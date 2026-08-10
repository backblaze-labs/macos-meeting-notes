"""Configured-root behavior for Backup snapshot capture."""

from pathlib import Path

from meeting_memory.service.backup_revision import capture_backup_snapshot

TRANSCRIPT = b"""---
schema_version: 2
created_by: meeting-memory
id: sample
backup_status: pending
b2_audio: null
b2_transcript: null
backup_uploaded_revision: null
---
# Transcript
"""


def test_default_snapshot_root_uses_canonical_configured_root_symlink(
    tmp_path: Path,
) -> None:
    real_root = tmp_path / "real-meetings"
    meeting = real_root / "sample"
    meeting.mkdir(parents=True)
    (meeting / "recording.m4a").write_bytes(b"private audio")
    (meeting / "transcript.md").write_bytes(TRANSCRIPT)
    configured_root = tmp_path / "configured-meetings"
    configured_root.symlink_to(real_root, target_is_directory=True)

    snapshot = capture_backup_snapshot(configured_root / "sample")

    assert snapshot.directory.parent == (
        real_root / ".meeting-memory-staging" / "backup-snapshots"
    )
    assert snapshot.audio_path.read_bytes() == b"private audio"
    snapshot.cleanup()

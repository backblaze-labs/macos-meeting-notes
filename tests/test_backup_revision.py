"""Golden and mutation tests for schema-v2 Backup revisions."""

from __future__ import annotations

import os
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from meeting_memory.service.backup_revision import (
    backup_revision,
    capture_backup_snapshot,
    compute_backup_revision,
    compute_backup_revision_with_transcript,
    normalize_transcript_for_backup,
)

LF_TRANSCRIPT = b"""---
schema_version: 2
created_by: meeting-memory
id: sample
backup_status: pending
b2_audio: null
b2_transcript: null
backup_uploaded_revision: null
---
# Transcript

backup_status: body text remains
"""


def test_backup_revision_golden_vector_and_line_endings() -> None:
    assert backup_revision(b"audio\x00bytes", LF_TRANSCRIPT) == (
        "fe05ee6cc4c556db72b4b540e59e7ca7eeced82c216aac5c6ae7e05093f0f4b9"
    )
    crlf_revision = backup_revision(
        b"audio\x00bytes", LF_TRANSCRIPT.replace(b"\n", b"\r\n")
    )
    assert crlf_revision == backup_revision(b"audio\x00bytes", LF_TRANSCRIPT)
    normalized = normalize_transcript_for_backup(LF_TRANSCRIPT + b"\n\n")
    assert normalized.endswith(b"\n")
    assert not normalized.endswith(b"\n\n")
    assert b"backup_status: body text remains" in normalized


def test_only_four_backup_fields_are_revision_neutral() -> None:
    baseline = backup_revision(b"audio", LF_TRANSCRIPT)
    changed_bookkeeping = (
        LF_TRANSCRIPT.replace(b"backup_status: pending", b"backup_status: succeeded")
        .replace(b"b2_audio: null", b"b2_audio: key")
        .replace(b"b2_transcript: null", b"b2_transcript: key")
        .replace(b"backup_uploaded_revision: null", b"backup_uploaded_revision: abc")
    )
    assert backup_revision(b"audio", changed_bookkeeping) == baseline
    assert backup_revision(b"changed", LF_TRANSCRIPT) != baseline
    changed_id = LF_TRANSCRIPT.replace(b"id: sample", b"id: changed")
    assert backup_revision(b"audio", changed_id) != baseline
    assert backup_revision(b"audio", LF_TRANSCRIPT + b"meaningful\n") != baseline


def test_file_revision_matches_bytes_and_snapshot_is_immutable_copy(tmp_path: Path) -> None:
    audio = tmp_path / "recording.m4a"
    transcript = tmp_path / "transcript.md"
    audio.write_bytes(b"original audio")
    transcript.write_bytes(LF_TRANSCRIPT)
    expected = backup_revision(audio.read_bytes(), transcript.read_bytes())

    snapshot = capture_backup_snapshot(audio, transcript, tmp_path / "snapshots")
    audio.write_bytes(b"mutated audio")
    transcript.write_bytes(LF_TRANSCRIPT + b"mutated\n")

    assert snapshot.revision == expected
    assert compute_backup_revision(snapshot.audio_path, snapshot.transcript_path) == expected
    assert snapshot.audio_path.read_bytes() == b"original audio"
    assert snapshot.transcript_path.read_bytes() == LF_TRANSCRIPT
    with pytest.raises(FrozenInstanceError):
        snapshot.revision = "changed"  # type: ignore[misc]
    directory = snapshot.directory
    snapshot.cleanup()
    assert not directory.exists()


def test_multiline_bookkeeping_is_removed_but_significant_multiline_is_preserved() -> None:
    transcript = b"""---
schema_version: 2
b2_audio: |-
  first/key

  continued
description: |-
  meaningful
  value
backup_status: pending
---
# Transcript
"""
    changed_bookkeeping = transcript.replace(b"first/key", b"other/key").replace(
        b"continued", b"also-changed"
    )
    changed_significant = transcript.replace(b"meaningful", b"different")

    assert backup_revision(b"audio", changed_bookkeeping) == backup_revision(
        b"audio", transcript
    )
    assert backup_revision(b"audio", changed_significant) != backup_revision(
        b"audio", transcript
    )
    normalized = normalize_transcript_for_backup(transcript)
    assert b"first/key" not in normalized
    assert b"continued" not in normalized
    assert b"description: |-\n  meaningful\n  value" in normalized


def test_blank_after_scalar_bookkeeping_is_preserved_as_meaningful_bytes() -> None:
    one_blank = b"""---
schema_version: 2
b2_audio: null

created_by: meeting-memory
---
# Transcript
"""
    two_blanks = one_blank.replace(
        b"b2_audio: null\n\n", b"b2_audio: null\n\n\n"
    )

    assert normalize_transcript_for_backup(one_blank) != normalize_transcript_for_backup(
        two_blanks
    )
    assert backup_revision(b"audio", one_blank) != backup_revision(b"audio", two_blanks)


def test_blank_after_empty_bookkeeping_field_is_preserved() -> None:
    one_blank = b"""---
schema_version: 2
b2_audio:

created_by: meeting-memory
---
# Transcript
"""
    two_blanks = one_blank.replace(b"b2_audio:\n\n", b"b2_audio:\n\n\n")

    assert backup_revision(b"audio", one_blank) != backup_revision(b"audio", two_blanks)


@pytest.mark.parametrize("invalid_source", ["audio-symlink", "transcript-symlink"])
def test_revision_and_snapshot_never_follow_private_source_symlinks(
    tmp_path: Path,
    invalid_source: str,
) -> None:
    private = tmp_path / "PRIVATE"
    private.write_bytes(LF_TRANSCRIPT if invalid_source == "transcript-symlink" else b"secret")
    audio = tmp_path / "recording.m4a"
    transcript = tmp_path / "transcript.md"
    audio.write_bytes(b"audio")
    transcript.write_bytes(LF_TRANSCRIPT)
    target = audio if invalid_source == "audio-symlink" else transcript
    target.unlink()
    target.symlink_to(private)
    snapshot_root = tmp_path / "snapshots"

    with pytest.raises((OSError, ValueError)):
        compute_backup_revision(audio, transcript)
    if invalid_source == "audio-symlink":
        with pytest.raises((OSError, ValueError)):
            compute_backup_revision_with_transcript(audio, LF_TRANSCRIPT)
    with pytest.raises((OSError, ValueError)):
        capture_backup_snapshot(audio, transcript, snapshot_root)

    assert private.read_bytes() == (
        LF_TRANSCRIPT if invalid_source == "transcript-symlink" else b"secret"
    )
    assert not snapshot_root.exists()


@pytest.mark.parametrize("nonregular", ["fifo", "directory"])
def test_nonregular_sources_are_rejected_without_snapshot_artifacts(
    tmp_path: Path,
    nonregular: str,
) -> None:
    audio = tmp_path / "recording.m4a"
    transcript = tmp_path / "transcript.md"
    transcript.write_bytes(LF_TRANSCRIPT)
    if nonregular == "fifo":
        os.mkfifo(audio)
    else:
        audio.mkdir()
    snapshot_root = tmp_path / "snapshots"

    with pytest.raises((OSError, ValueError)):
        compute_backup_revision(audio, transcript)
    with pytest.raises((OSError, ValueError)):
        capture_backup_snapshot(audio, transcript, snapshot_root)

    assert not snapshot_root.exists()

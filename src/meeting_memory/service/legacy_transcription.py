"""Explicit legacy retry attempts, sealed to pinned metadata and audio bytes."""

from __future__ import annotations

import os
import re
import uuid
from dataclasses import replace

from meeting_memory.service.frontmatter import merge_frontmatter_fields
from meeting_memory.service.legacy_snapshot import (
    capture_legacy_document_snapshot,
    replace_legacy_metadata,
)
from meeting_memory.service.meeting_locks import meeting_lock
from meeting_memory.service.pinned_fs import open_directory_tree
from meeting_memory.service.transcription_attempts import stream_digest


def claim_legacy_attempt(snapshot, provider, *, resume_id=None):
    """Bind a fresh attempt before the adapter receives the private audio."""
    identity = _audio_identities(snapshot)
    attempt_id = (
        snapshot.frontmatter.get("transcription_attempt_id") if resume_id else uuid.uuid4().hex
    )
    if resume_id is not None and (
        provider.value != "assemblyai"
        or snapshot.frontmatter.get("transcription_provider") != "assemblyai"
        or snapshot.frontmatter.get("assemblyai_id") != resume_id
        or not isinstance(attempt_id, str)
        or re.fullmatch(r"[0-9a-f]{32}", attempt_id) is None
        or snapshot.frontmatter.get("transcription_audio_sha256") != identity[0][3]
        or snapshot.frontmatter.get("transcription_audio_size") != identity[0][2]
    ):
        raise ValueError("The legacy remote attempt no longer matches its recording")
    text = merge_frontmatter_fields(
        snapshot.metadata_text,
        {
            "transcription_provider": provider.value,
            "transcription_attempt_id": attempt_id,
            "transcription_status": "running",
            "assemblyai_id": resume_id,
            "transcription_audio_sha256": identity[0][3],
            "transcription_audio_size": identity[0][2],
        },
    )
    with meeting_lock(snapshot.directory.parent, snapshot.directory.name):
        replace_legacy_metadata(snapshot, text)
        updated = _rebind_legacy_snapshot(snapshot, text)
    return updated, identity, attempt_id


def record_legacy_provider_id(snapshot, identities, identifier):
    if not isinstance(identifier, str) or not identifier.strip():
        raise ValueError("The provider returned no usable job ID")
    if snapshot.frontmatter.get("transcription_provider") != "assemblyai":
        raise ValueError("Local attempts cannot have a remote job ID")
    text = merge_frontmatter_fields(snapshot.metadata_text, {"assemblyai_id": identifier.strip()})
    with meeting_lock(snapshot.directory.parent, snapshot.directory.name):
        if _audio_identities(snapshot) != identities:
            raise ValueError("Legacy audio changed before recording its provider job")
        replace_legacy_metadata(snapshot, text)
        return _rebind_legacy_snapshot(snapshot, text)


def _rebind_legacy_snapshot(snapshot, expected_text):
    with capture_legacy_document_snapshot(snapshot.directory) as claimed:
        if claimed.metadata_text != expected_text:
            raise ValueError("Legacy attempt changed before processing")
        return replace(
            snapshot,
            metadata_device=claimed.metadata_device,
            metadata_inode=claimed.metadata_inode,
            metadata_text=claimed.metadata_text,
            frontmatter=claimed.frontmatter,
        )


def finish_legacy_attempt(snapshot, identities, text):
    with meeting_lock(snapshot.directory.parent, snapshot.directory.name):
        if _audio_identities(snapshot) != identities:
            raise ValueError("Legacy audio changed while processing")
        replace_legacy_metadata(snapshot, text)


def defer_legacy_attempt(snapshot, identities, *, state):
    finish_legacy_attempt(
        snapshot,
        identities,
        merge_frontmatter_fields(
            snapshot.metadata_text,
            {"transcription_status": state},
        ),
    )


def _audio_identities(snapshot):
    root_fd = open_directory_tree(snapshot.directory.parent.resolve(strict=True))
    directory_fd = -1
    try:
        directory_fd = os.open(
            snapshot.directory.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd
        )
        directory = os.fstat(directory_fd)
        if (directory.st_dev, directory.st_ino) != (
            snapshot.directory_device,
            snapshot.directory_inode,
        ):
            raise ValueError("Legacy directory changed before processing")
        identities = []
        for audio in snapshot.audio:
            descriptor = os.open(
                audio.filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd
            )
            try:
                info = os.fstat(descriptor)
                copied = os.fstat(audio.stream.fileno())
                digest = stream_digest(descriptor, info.st_size)
                if info.st_size != copied.st_size or digest != stream_digest(
                    audio.stream.fileno(), copied.st_size
                ):
                    raise ValueError("Legacy source differs from its private snapshot")
                visible = os.stat(audio.filename, dir_fd=directory_fd, follow_symlinks=False)
                after = os.fstat(descriptor)
                before = (
                    info.st_dev,
                    info.st_ino,
                    info.st_size,
                    info.st_mtime_ns,
                    info.st_ctime_ns,
                )
                current = (
                    after.st_dev,
                    after.st_ino,
                    after.st_size,
                    after.st_mtime_ns,
                    after.st_ctime_ns,
                )
                if before != current or (visible.st_dev, visible.st_ino) != before[:2]:
                    raise ValueError("Legacy source changed during validation")
                identities.append((info.st_dev, info.st_ino, info.st_size, digest))
            finally:
                os.close(descriptor)
        return tuple(identities)
    finally:
        if directory_fd >= 0:
            os.close(directory_fd)
        os.close(root_fd)

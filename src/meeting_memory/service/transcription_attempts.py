"""Atomic provider/attempt claims and immutable source-audio identity checks."""

from __future__ import annotations

import hashlib
import os
import stat
import uuid
from pathlib import Path

from meeting_memory.service.frontmatter import merge_frontmatter_fields
from meeting_memory.service.markdown import render_transcription_failure_body, safe_frontmatter_text
from meeting_memory.service.meeting_document import (
    open_meeting_document,
    require_meeting_directory_identity,
)
from meeting_memory.service.meeting_locks import meeting_lock
from meeting_memory.service.meeting_state import MeetingStateConflict
from meeting_memory.types.transcription import (
    TranscriptionAttempt,
    TranscriptionAudioIdentity,
    TranscriptionProvider,
)


class TranscriptionSourceChanged(MeetingStateConflict):
    def __init__(self, attempt_id):
        super().__init__("Source audio differs from the submitted remote job")
        self.attempt_id = attempt_id


def fail_changed_remote_source(meetings_dir, handle, resume_id, changed):
    summary = "Recording changed since the previous attempt."
    action = "Retry again to transcribe the current saved recording."
    with meeting_lock(meetings_dir, handle.files.meta.slug):
        with open_meeting_document(meetings_dir, handle.files.directory) as document:
            require_meeting_directory_identity(document, handle.directory_identity)
            current = document.frontmatter
            if (
                current.get("transcription_status") != "running"
                or current.get("transcription_provider") != "assemblyai"
                or current.get("transcription_attempt_id") != changed.attempt_id
                or current.get("assemblyai_id") != resume_id
            ):
                raise MeetingStateConflict("The remote attempt was replaced")
            replace_reconciled(
                document,
                {"transcription_status": "failed"},
                body=render_transcription_failure_body(summary=summary, action=action),
            )
    return summary, action


def claim_attempt(meetings_dir, handle, provider, *, resume_id=None) -> TranscriptionAttempt:
    with meeting_lock(meetings_dir, handle.files.meta.slug):
        with open_meeting_document(meetings_dir, handle.files.directory) as document:
            require_meeting_directory_identity(document, handle.directory_identity)
            current = document.frontmatter
            meta = handle.files.meta
            expected = {
                "id": meta.slug,
                "date": meta.started_at.isoformat(),
                "duration_minutes": meta.duration_minutes,
                "calendar_title": safe_frontmatter_text(meta.calendar_title),
            }
            if any(current.get(key) != value for key, value in expected.items()):
                raise MeetingStateConflict("Meeting metadata changed before transcription")
            if resume_id is None:
                if current.get("transcription_status") != "pending":
                    raise MeetingStateConflict("Transcription is no longer pending")
            elif (
                provider is not TranscriptionProvider.ASSEMBLYAI
                or current.get("transcription_status") != "running"
                or current.get("assemblyai_id") != resume_id
                or current.get("transcription_provider") not in {None, "assemblyai"}
            ):
                raise MeetingStateConflict("The remote job no longer matches this attempt")
            identity = audio_identity(document)
            stored_attempt = current.get("transcription_attempt_id") if resume_id else None
            if stored_attempt is not None and (
                current.get("transcription_audio_sha256") != identity.sha256
                or current.get("transcription_audio_size") != identity.size
            ):
                raise TranscriptionSourceChanged(stored_attempt)
            attempt = TranscriptionAttempt(provider, stored_attempt or uuid.uuid4().hex, identity)
            replace_reconciled(
                document,
                {
                    "transcription_status": "running",
                    "transcription_provider": provider.value,
                    "transcription_attempt_id": attempt.attempt_id,
                    "transcription_audio_sha256": identity.sha256,
                    "transcription_audio_size": identity.size,
                    "assemblyai_id": resume_id
                    if provider is TranscriptionProvider.ASSEMBLYAI
                    else None,
                },
            )
            return attempt


def require_attempt(document, attempt: TranscriptionAttempt | None) -> None:
    stored = document.frontmatter.get("transcription_attempt_id")
    provider = document.frontmatter.get("transcription_provider")
    if attempt is None:
        if stored is not None:
            raise MeetingStateConflict("Transcription completion requires its attempt identity")
        return
    if stored != attempt.attempt_id or provider != attempt.provider.value:
        raise MeetingStateConflict("Transcription attempt was replaced")
    if attempt.audio_identity is not None and audio_identity(document) != attempt.audio_identity:
        raise MeetingStateConflict("Source audio changed during transcription")


def check_attempt_source(meetings_dir, handle, attempt):
    with meeting_lock(meetings_dir, handle.files.meta.slug):
        with open_meeting_document(meetings_dir, handle.files.directory) as document:
            require_meeting_directory_identity(document, handle.directory_identity)
            require_attempt(document, attempt)
            if document.frontmatter.get("transcription_status") != "running":
                raise MeetingStateConflict("Transcription is no longer running")


def defer_attempt(meetings_dir: Path, handle, attempt: TranscriptionAttempt) -> None:
    with meeting_lock(meetings_dir, handle.files.meta.slug):
        with open_meeting_document(meetings_dir, handle.files.directory) as document:
            require_meeting_directory_identity(document, handle.directory_identity)
            require_attempt(document, attempt)
            if document.frontmatter.get("transcription_status") != "running":
                raise MeetingStateConflict("Transcription is no longer running")
            replace_reconciled(document, {"transcription_status": "pending"})


def replace_reconciled(document, updates, *, body=None) -> None:
    prospective = merge_frontmatter_fields(document.text, updates)
    if body is not None:
        lines = prospective.splitlines(keepends=True)
        closing = next(
            index for index, line in enumerate(lines[1:], start=1) if line.rstrip("\r\n") == "---"
        )
        prospective = "".join(lines[: closing + 1]).rstrip("\r\n") + "\n\n" + body.rstrip() + "\n"
    if document.frontmatter.get("backup_status") == "succeeded" and (
        document.backup_revision(prospective)
        != document.frontmatter.get("backup_uploaded_revision")
    ):
        prospective = merge_frontmatter_fields(prospective, {"backup_status": "pending"})
    document.replace_transcript(prospective)


def audio_identity(document) -> TranscriptionAudioIdentity:
    descriptor = os.open(
        "recording.m4a", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=document.directory_fd
    )
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size <= 0:
            raise MeetingStateConflict("Source audio is not a regular nonempty file")
        digest = stream_digest(descriptor, before.st_size)
        after = os.fstat(descriptor)
        visible = os.stat("recording.m4a", dir_fd=document.directory_fd, follow_symlinks=False)

        def identity(info):
            return (
                info.st_dev,
                info.st_ino,
                info.st_size,
                info.st_mtime_ns,
                info.st_ctime_ns,
            )

        if identity(before) != identity(after) or identity(after) != identity(visible):
            raise MeetingStateConflict("Source audio changed while checking its identity")
        return TranscriptionAudioIdentity(after.st_dev, after.st_ino, after.st_size, digest)
    finally:
        os.close(descriptor)


def stream_digest(descriptor: int, size: int) -> str:
    digest = hashlib.sha256()
    for offset in range(0, size, 1024 * 1024):
        chunk = os.pread(descriptor, min(1024 * 1024, size - offset), offset)
        if not chunk:
            raise MeetingStateConflict("Source audio changed while checking its contents")
        digest.update(chunk)
    return digest.hexdigest()

"""Serialization for durable recovery publication identities."""

from __future__ import annotations

from meeting_memory.types.meeting import PostCommitPolicy, validate_meeting_slug
from meeting_memory.types.recovery import RecoveryPublication


def publication_payload(publication: RecoveryPublication) -> dict[str, object]:
    return {
        "status": "published",
        "slug": publication.slug,
        "directory_device": publication.directory_device,
        "directory_inode": publication.directory_inode,
        "audio_device": publication.audio_device,
        "audio_inode": publication.audio_inode,
        "audio_size": publication.audio_size,
        "audio_sha256": publication.audio_sha256,
        "source_device": publication.source_device,
        "source_inode": publication.source_inode,
        "source_size": publication.source_size,
        "source_sha256": publication.source_sha256,
        "transcription": publication.policy.transcription,
        "backup": publication.policy.backup,
    }


def publication_from_payload(value: object) -> RecoveryPublication | None:
    if value is None:
        return None
    if not isinstance(value, dict) or value.get("status") not in {
        "published",
        "durability_uncertain",
    }:
        raise ValueError("recovery publication state is invalid")
    slug = validate_meeting_slug(str(value["slug"]))
    audio_digest = str(value["audio_sha256"])
    source_digest = str(value["source_sha256"])
    if len(audio_digest) != 64 or len(source_digest) != 64:
        raise ValueError("recovery publication digest is invalid")
    return RecoveryPublication(
        slug,
        int(value["directory_device"]),
        int(value["directory_inode"]),
        int(value["audio_device"]),
        int(value["audio_inode"]),
        int(value["audio_size"]),
        audio_digest,
        int(value["source_device"]),
        int(value["source_inode"]),
        int(value["source_size"]),
        source_digest,
        PostCommitPolicy(value.get("transcription") is True, value.get("backup") is True),
    )

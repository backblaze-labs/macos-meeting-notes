"""Pure canonical Backup revision normalization and hash framing."""

from __future__ import annotations

import hashlib
import json
import re
from typing import BinaryIO

from meeting_memory.types.meeting import validate_meeting_slug

BACKUP_REVISION_DOMAIN = b"meeting-memory-backup-v2\0"
EXCLUDED_FRONTMATTER_FIELDS = frozenset(
    {"backup_status", "b2_audio", "b2_transcript", "backup_uploaded_revision"}
)
TOP_LEVEL_FIELD = re.compile(r"^([A-Za-z0-9_-]+):(?:[ \t]*(.*))?$")


def owned_backup_transcript_slug(transcript: bytes | str) -> str:
    """Return the owned schema-v2 identity from one pinned transcript snapshot."""

    raw = transcript.decode("utf-8") if isinstance(transcript, bytes) else transcript
    lines = raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if not lines or lines[0] != "---":
        raise ValueError("backup transcript is missing top-level frontmatter")
    identity: dict[str, object] = {}
    for line in lines[1:]:
        if line == "---":
            break
        match = TOP_LEVEL_FIELD.match(line)
        if match and match.group(1) in {"schema_version", "created_by", "id"}:
            identity[match.group(1)] = _parse_scalar((match.group(2) or "").strip())
    else:
        raise ValueError("backup transcript frontmatter is not closed")
    if identity.get("schema_version") != 2 or identity.get("created_by") != "meeting-memory":
        raise ValueError("backup snapshot requires an owned schema-v2 transcript")
    slug = identity.get("id")
    if not isinstance(slug, str):
        raise ValueError("backup transcript id must be a string")
    return validate_meeting_slug(slug)


def normalize_backup_transcript(transcript: bytes | str) -> bytes:
    raw = transcript.encode("utf-8") if isinstance(transcript, str) else transcript
    text = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    if not lines or lines[0] != "---":
        raise ValueError("transcript is missing top-level YAML frontmatter")

    output = ["---"]
    skipping = False
    closing = None
    for index, line in enumerate(lines[1:], start=1):
        if line == "---":
            output.append(line)
            closing = index
            break
        match = TOP_LEVEL_FIELD.match(line)
        if match:
            excluded = match.group(1) in EXCLUDED_FRONTMATTER_FIELDS
            skipping = excluded and (match.group(2) or "").strip().startswith(("|", ">"))
            if not excluded:
                output.append(line)
            continue
        if skipping and (line.startswith((" ", "\t")) or not line):
            continue
        skipping = False
        output.append(line)
    if closing is None:
        raise ValueError("transcript YAML frontmatter is not closed")
    output.extend(lines[closing + 1 :])
    return ("\n".join(output).rstrip("\n") + "\n").encode("utf-8")


def backup_revision_bytes(audio: bytes, transcript: bytes | str) -> str:
    normalized = normalize_backup_transcript(transcript)
    digest = hashlib.sha256()
    digest.update(BACKUP_REVISION_DOMAIN)
    digest.update(len(audio).to_bytes(8, "big", signed=False))
    digest.update(audio)
    digest.update(len(normalized).to_bytes(8, "big", signed=False))
    digest.update(normalized)
    return digest.hexdigest()


def backup_revision_stream(
    audio: BinaryIO,
    audio_size: int,
    transcript: bytes | str,
) -> str:
    normalized = normalize_backup_transcript(transcript)
    digest = hashlib.sha256()
    digest.update(BACKUP_REVISION_DOMAIN)
    digest.update(audio_size.to_bytes(8, "big", signed=False))
    audio.seek(0)
    while chunk := audio.read(1024 * 1024):
        digest.update(chunk)
    audio.seek(0)
    digest.update(len(normalized).to_bytes(8, "big", signed=False))
    digest.update(normalized)
    return digest.hexdigest()


def _parse_scalar(value: str) -> object:
    if value.startswith('"'):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("backup transcript identity is invalid") from exc
    if value.isdigit():
        return int(value)
    return value

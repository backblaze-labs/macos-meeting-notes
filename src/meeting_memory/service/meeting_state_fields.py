"""Field-ownership rules for schema-v2 state updates."""

from __future__ import annotations

from collections.abc import Mapping

from meeting_memory.types.artifacts import ArtifactFieldOwner

OWNER_FIELDS = {
    ArtifactFieldOwner.CORE: frozenset(
        {"schema_version", "created_by", "id", "date", "duration_minutes", "calendar_title"}
    ),
    ArtifactFieldOwner.TRANSCRIPTION: frozenset(
        {"assemblyai_id", "transcription_status", "participants"}
    ),
    ArtifactFieldOwner.SPEAKERS: frozenset(
        {"speaker_candidates", "speaker_aliases", "speaker_status"}
    ),
    ArtifactFieldOwner.BACKUP: frozenset(
        {"b2_audio", "b2_transcript", "backup_status", "backup_uploaded_revision"}
    ),
}
IMMUTABLE_CORE_FIELDS = frozenset({"schema_version", "created_by", "id", "date"})


def validate_owned_fields(owner: ArtifactFieldOwner, updates: Mapping[str, object]) -> None:
    unknown = set(updates) - OWNER_FIELDS[owner]
    if unknown:
        raise ValueError(f"{owner.value} does not own fields: {sorted(unknown)}")
    if set(updates) & {"transcription_status", "backup_status"}:
        raise ValueError("job states must use transition_job compare-and-set")


def validate_core_identity(
    owner: ArtifactFieldOwner,
    current: Mapping[str, object],
    updates: Mapping[str, object],
) -> None:
    if owner is not ArtifactFieldOwner.CORE:
        return
    changed = {
        key for key in IMMUTABLE_CORE_FIELDS & set(updates) if current.get(key) != updates[key]
    }
    if changed:
        raise ValueError(f"immutable meeting identity fields cannot change: {sorted(changed)}")


def changed_fields(
    current: Mapping[str, object],
    updates: Mapping[str, object],
) -> dict[str, object]:
    return {key: value for key, value in updates.items() if current.get(key) != value}

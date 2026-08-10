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
        {"speaker_candidates"}
    ),
    ArtifactFieldOwner.BACKUP: frozenset(),
}
IMMUTABLE_CORE_FIELDS = frozenset({"schema_version", "created_by", "id", "date"})


def validate_owned_fields(owner: ArtifactFieldOwner, updates: Mapping[str, object]) -> None:
    unknown = set(updates) - OWNER_FIELDS[owner]
    if unknown:
        raise ValueError(f"{owner.value} does not own fields: {sorted(unknown)}")
    if set(updates) & {"transcription_status", "backup_status"}:
        raise ValueError("job states must use transition_job compare-and-set")
    for field, value in updates.items():
        _validate_field_value(field, value)


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


def _validate_field_value(field: str, value: object) -> None:
    if field == "schema_version" and (not isinstance(value, int) or isinstance(value, bool)):
        raise ValueError("schema_version must be an integer")
    if field in {"created_by", "id", "date", "calendar_title"} and not isinstance(
        value, str
    ):
        raise ValueError(f"{field} must be a string")
    if field == "duration_minutes" and (
        not isinstance(value, int) or isinstance(value, bool) or value < 0
    ):
        raise ValueError("duration_minutes must be a non-negative integer")
    if field == "assemblyai_id" and not (
        value is None or isinstance(value, str) and value.strip()
    ):
        raise ValueError("assemblyai_id must be null or a non-blank string")
    if field in {"participants", "speaker_candidates"} and not (
        isinstance(value, list) and all(isinstance(item, str) for item in value)
    ):
        raise ValueError(f"{field} must be a list of strings")

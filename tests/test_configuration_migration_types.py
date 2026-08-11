"""Public Stage 4C migration boundary tests."""

from __future__ import annotations

from dataclasses import asdict

import pytest

from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration import SettingKey
from meeting_memory.types.configuration_migration import (
    MigrationCandidate,
    MigrationConfirmation,
    MigrationField,
    MigrationFieldState,
    MigrationOutcome,
    MigrationOutcomeState,
    MigrationPreview,
    MigrationPreviewId,
    MigrationPreviewState,
)


def test_preview_and_outcome_are_canonical_and_value_free() -> None:
    preview_id = MigrationPreviewId("a" * 32)
    candidates = tuple(
        MigrationCandidate(
            capability,
            tuple(
                MigrationField(
                    capability,
                    key,
                    MigrationFieldState.ABSENT,
                    key
                    in {
                        SettingKey.ASSEMBLYAI_API_KEY,
                        SettingKey.B2_APPLICATION_KEY_ID,
                        SettingKey.B2_APPLICATION_KEY,
                        SettingKey.ANTHROPIC_API_KEY,
                    },
                )
                for key in reversed(_keys_for(capability))
            ),
            False,
        )
        for capability in reversed(tuple(Capability))
    )
    preview = MigrationPreview(
        preview_id,
        MigrationPreviewState.EMPTY,
        candidates,
        "No recognized values are available.",
        "Keep using legacy configuration or open a new preview later.",
    )
    outcome = MigrationOutcome(
        MigrationOutcomeState.REJECTED,
        (Capability.NOTES, Capability.BACKUP),
        "Migration was not applied.",
        "Open a new preview and confirm a selection.",
    )

    assert tuple(item.capability for item in preview.candidates) == tuple(Capability)
    assert tuple(field.key for field in preview.candidates[0].fields) == (
        SettingKey.MEETINGS_DIR,
        SettingKey.MAX_RECORDING_MINUTES,
    )
    assert outcome.selected == (Capability.BACKUP, Capability.NOTES)
    assert "a" * 32 not in repr(preview)
    assert "a" * 32 not in str(preview.preview_id)
    assert "a" * 32 not in repr(asdict(preview))
    assert outcome.activated is False


def test_confirmation_is_typed_nonempty_unique_and_canonical() -> None:
    preview_id = MigrationPreviewId("b" * 32)
    confirmation = MigrationConfirmation(
        preview_id,
        (Capability.NOTES, Capability.RECORDING_CORE),
        True,
    )

    assert confirmation.selected == (Capability.RECORDING_CORE, Capability.NOTES)
    with pytest.raises(ValueError, match="non-empty"):
        MigrationConfirmation(preview_id, (), True)
    with pytest.raises(ValueError, match="non-empty"):
        MigrationConfirmation(preview_id, (Capability.BACKUP, Capability.BACKUP), True)
    with pytest.raises(ValueError, match="typed"):
        MigrationConfirmation(preview_id, ("backup",), True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="typed"):
        MigrationConfirmation(preview_id, (Capability.BACKUP,), 1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="typed"):
        MigrationConfirmation(preview_id, (Capability.BACKUP,), False)


def test_preview_id_is_opaque_strict_and_immutable() -> None:
    preview_id = MigrationPreviewId("c" * 32)

    assert preview_id == MigrationPreviewId("c" * 32)
    with pytest.raises(ValueError, match="invalid"):
        MigrationPreviewId("visible-source-digest")
    with pytest.raises(AttributeError, match="immutable"):
        preview_id._value = "d" * 32  # type: ignore[misc]


def test_fields_reject_false_capability_or_secret_classification() -> None:
    with pytest.raises(ValueError, match="belong"):
        MigrationField(
            Capability.BACKUP,
            SettingKey.ASSEMBLYAI_API_KEY,
            MigrationFieldState.ABSENT,
            True,
        )
    with pytest.raises(ValueError, match="secret classification"):
        MigrationField(
            Capability.TRANSCRIPTION,
            SettingKey.ASSEMBLYAI_API_KEY,
            MigrationFieldState.ABSENT,
            False,
        )


def _keys_for(capability: Capability) -> tuple[SettingKey, ...]:
    return {
        Capability.RECORDING_CORE: (
            SettingKey.MEETINGS_DIR,
            SettingKey.MAX_RECORDING_MINUTES,
        ),
        Capability.TRANSCRIPTION: (SettingKey.ASSEMBLYAI_API_KEY,),
        Capability.BACKUP: (
            SettingKey.B2_APPLICATION_KEY_ID,
            SettingKey.B2_APPLICATION_KEY,
            SettingKey.B2_ENDPOINT,
            SettingKey.B2_REGION,
            SettingKey.B2_BUCKET_NAME,
        ),
        Capability.CALENDAR: (
            SettingKey.GOOGLE_CALENDAR_CREDENTIALS_FILE,
            SettingKey.GOOGLE_CALENDAR_ID,
            SettingKey.KNOWN_SPEAKERS,
            SettingKey.NOTIFY_MINUTES_BEFORE,
            SettingKey.CALENDAR_POLL_INTERVAL,
        ),
        Capability.NOTES: (
            SettingKey.ANTHROPIC_API_KEY,
            SettingKey.ANTHROPIC_MODEL,
            SettingKey.SUMMARY_PROMPT_FILE,
        ),
    }[capability]

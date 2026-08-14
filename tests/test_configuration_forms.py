"""Copy, secret handling, and value-free preview tests for native forms."""

from __future__ import annotations

import inspect

import pytest
from configuration_surface_fakes import configuration_view

from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration import SecretId, SettingKey
from meeting_memory.types.configuration_editing import CapabilityConfiguration
from meeting_memory.types.configuration_migration import (
    MigrationCandidate,
    MigrationField,
    MigrationFieldState,
)
from meeting_memory.ui.configuration_forms import (
    DISCLOSURES,
    configuration_change,
    open_configuration_form,
    requires_disclosure,
    source_status,
)
from meeting_memory.ui.migration_form import migration_detail, open_migration_preview


def test_disclosures_name_provider_payload_and_trigger() -> None:
    assert "AssemblyAI" in DISCLOSURES[Capability.TRANSCRIPTION]
    assert "meeting audio" in DISCLOSURES[Capability.TRANSCRIPTION]
    assert "after recording stops" in DISCLOSURES[Capability.TRANSCRIPTION]
    assert "Backblaze B2" in DISCLOSURES[Capability.BACKUP]
    assert "recording.m4a and transcript.md" in DISCLOSURES[Capability.BACKUP]
    assert "automatically" in DISCLOSURES[Capability.BACKUP]
    assert "Google Calendar" in DISCLOSURES[Capability.CALENDAR]
    assert "read-only Google Calendar API polling" in DISCLOSURES[Capability.CALENDAR]
    assert "explicit Authorize action" in DISCLOSURES[Capability.CALENDAR]
    notes = DISCLOSURES[Capability.NOTES]
    assert "Anthropic" in notes
    assert "fixed output-schema instructions" in notes
    assert "instruction block" in notes
    assert "layout stays local" in notes
    assert "speaker-confirmed transcript excerpt" in notes
    assert "60,000 characters" in notes
    assert "explicit speaker confirmation" in notes


def test_optional_enable_and_false_to_compatibility_require_disclosure() -> None:
    view = configuration_view(Capability.NOTES)

    assert requires_disclosure(view, True) is True
    assert requires_disclosure(view, None) is True
    assert requires_disclosure(view, False) is False


def test_source_status_keeps_process_and_legacy_truth_value_free() -> None:
    base = configuration_view(Capability.BACKUP)
    view = CapabilityConfiguration(
        base.edit_id,
        base.capability,
        False,
        base.fields,
        base.secret_availability,
        True,
        True,
        True,
        True,
    )

    text = source_status(view)

    assert "legacy .env" in text
    assert "Process environment values override part" in text
    assert "will re-enable" in text
    assert "sentinel" not in text.casefold()
    assert "secretref" not in text.casefold()


def test_secure_secret_groups_are_blank_preserving_and_atomic() -> None:
    view = configuration_view(Capability.BACKUP)
    values = {field.key: field.value.value for field in view.fields}
    values.update(
        {
            SettingKey.B2_APPLICATION_KEY_ID: "private-id",
            SettingKey.B2_APPLICATION_KEY: "private-key",
        }
    )

    change = configuration_change(view, True, values, True)

    assert change.secret is not None
    assert change.secret.secret_id is SecretId.BACKUP
    assert "private" not in repr(change)
    blank = {**values, SettingKey.B2_APPLICATION_KEY_ID: "", SettingKey.B2_APPLICATION_KEY: ""}
    assert configuration_change(view, False, blank, False).secret is None
    with pytest.raises(ValueError, match="together"):
        configuration_change(
            view,
            True,
            {**values, SettingKey.B2_APPLICATION_KEY: ""},
            True,
        )


def test_native_form_has_secure_controls_and_no_plain_secret_fallback() -> None:
    source = inspect.getsource(open_configuration_form)

    assert "NSSecureTextField" in source
    assert 'setStringValue_("")' in source
    assert "rumps.Window" not in source


def test_migration_detail_exposes_only_key_state_and_presence_flags() -> None:
    candidate = MigrationCandidate(
        Capability.BACKUP,
        (
            MigrationField(
                Capability.BACKUP,
                SettingKey.B2_ENDPOINT,
                MigrationFieldState.INVALID,
                False,
                True,
            ),
            MigrationField(
                Capability.BACKUP,
                SettingKey.B2_APPLICATION_KEY,
                MigrationFieldState.IMPORTABLE,
                True,
            ),
        ),
        False,
    )

    detail = migration_detail(candidate)

    assert "B2_ENDPOINT — invalid" in detail
    assert "process override present" in detail
    assert "B2_APPLICATION_KEY — importable · credential" in detail
    assert "private" not in detail
    source = inspect.getsource(open_migration_preview)
    assert "preview.candidates" in source
    assert "setEnabled_(candidate.selectable)" in source

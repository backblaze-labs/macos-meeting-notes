"""Local default and explicit external-consent decisions at the native form boundary."""

from dataclasses import replace

from configuration_surface_fakes import configuration_view

from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration import SettingKey
from meeting_memory.types.configuration_editing import ConfigurationField, ConfigurationValue
from meeting_memory.types.transcription import ASSEMBLYAI_CONSENT_VERSION, TranscriptionProvider
from meeting_memory.ui.transcription_form import (
    ASSEMBLYAI_NOTICE,
    DATA_BOUNDARIES,
    OFFICIAL_SOURCES,
    transcription_change,
)


def view():
    base = configuration_view(Capability.TRANSCRIPTION)
    values = {
        SettingKey.TRANSCRIPTION_PROVIDER: "local",
        SettingKey.ASSEMBLYAI_CONSENT: "not-accepted",
    }
    return replace(
        base,
        fields=tuple(
            ConfigurationField(key, ConfigurationValue(value)) for key, value in values.items()
        ),
    )


def test_local_save_requires_no_key_and_never_returns_entered_external_secret() -> None:
    change = transcription_change(
        view(), True, TranscriptionProvider.LOCAL, "secret-sentinel", False
    )
    assert change is not None
    assert change.secret is None
    assert change.enabled is True
    assert {field.key: field.value.value for field in change.fields} == {
        SettingKey.TRANSCRIPTION_PROVIDER: "local",
        SettingKey.ASSEMBLYAI_CONSENT: "not-accepted",
    }


def test_external_cancel_cannot_return_an_activated_change() -> None:
    assert (
        transcription_change(view(), True, TranscriptionProvider.ASSEMBLYAI, "key", False) is None
    )
    assert (
        transcription_change(view(), None, TranscriptionProvider.ASSEMBLYAI, "key", False) is None
    )


def test_external_confirmation_persists_version_and_secure_secret() -> None:
    change = transcription_change(view(), True, TranscriptionProvider.ASSEMBLYAI, "key", True)
    assert change is not None and change.secret is not None
    assert {field.key: field.value.value for field in change.fields}[
        SettingKey.ASSEMBLYAI_CONSENT
    ] == ASSEMBLYAI_CONSENT_VERSION
    assert change.disclosure_confirmed


def test_disabled_remains_disabled_without_external_acceptance() -> None:
    change = transcription_change(view(), False, TranscriptionProvider.ASSEMBLYAI, "", False)
    assert change is not None
    assert change.enabled is False
    assert {field.key: field.value.value for field in change.fields}[
        SettingKey.ASSEMBLYAI_CONSENT
    ] == "not-accepted"


def test_notice_explains_paid_opt_out_and_separate_egress() -> None:
    assert "audio leaves your Mac" in ASSEMBLYAI_NOTICE
    assert "free plan" in ASSEMBLYAI_NOTICE
    assert "cannot opt out" in ASSEMBLYAI_NOTICE
    assert "paid" in ASSEMBLYAI_NOTICE
    assert "not automatic" in ASSEMBLYAI_NOTICE
    assert "future requests" in ASSEMBLYAI_NOTICE
    assert "2026-10-27" in ASSEMBLYAI_NOTICE
    assert all(url.startswith("https://www.assemblyai.com/docs/") for _, url in OFFICIAL_SOURCES)
    for boundary in ("Hugging Face", "Backblaze B2", "Anthropic", "speaker suggestions"):
        assert boundary in DATA_BOUNDARIES


def test_compatibility_save_becomes_explicit_app_managed_selection() -> None:
    change = transcription_change(view(), None, TranscriptionProvider.LOCAL, "", False)
    assert change is not None and change.enabled is True


def test_disabling_external_ignores_any_typed_credential() -> None:
    change = transcription_change(view(), False, TranscriptionProvider.ASSEMBLYAI, "key", False)
    assert change is not None and change.enabled is False and change.secret is None

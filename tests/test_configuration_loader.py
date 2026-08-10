"""Scoped Stage 4B configuration composition and security tests."""

from __future__ import annotations

import threading
from dataclasses import asdict
from pathlib import Path

import pytest
from configuration_loader_fakes import (
    all_provider_preferences,
    issue_for,
    load_test_configuration,
    provider_preferences,
    source_for,
    write_env,
)

from meeting_memory.service import configuration_sources
from meeting_memory.service.configuration_loader import (
    ConfigurationLoadError,
    load_configuration,
)
from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration import (
    SecretId,
    SecretRef,
    SettingKey,
)
from meeting_memory.types.configuration_resolution import (
    ConfigurationIssueCode,
    ConfigurationUse,
    SettingSource,
)


def test_missing_preferences_preserve_legacy_parity_and_process_precedence(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env"
    original = b"MEETINGS_DIR=/legacy\nASSEMBLYAI_API_KEY=legacy-secret\n"
    env_file.write_bytes(original)

    loaded = load_test_configuration(
        ConfigurationUse.RUNTIME,
        env_file=env_file,
        process={"MEETINGS_DIR": "/process"},
    )

    assert loaded.meetings_dir_path == Path("/process")
    assert loaded.transcription is not None
    assert loaded.transcription.api_key == "legacy-secret"
    assert source_for(loaded, SettingKey.MEETINGS_DIR) is SettingSource.PROCESS_ENV
    assert env_file.read_bytes() == original


def test_explicit_disable_masks_legacy_values_and_never_reads_ref(tmp_path: Path) -> None:
    preferences, material = provider_preferences(
        SecretId.TRANSCRIPTION,
        enabled=False,
    )
    reads: list[SecretRef] = []

    loaded = load_test_configuration(
        ConfigurationUse.RUNTIME,
        preferences=preferences,
        env_file=write_env(tmp_path, {"ASSEMBLYAI_API_KEY": "legacy-secret"}),
        reader=lambda ref: reads.append(ref) or material,
    )

    assert loaded.capability_enabled(Capability.TRANSCRIPTION) is False
    assert loaded.transcription is None
    assert loaded.settings.assemblyai_api_key is None
    assert loaded.resolution.value_for(SettingKey.ASSEMBLYAI_API_KEY) == "legacy-secret"
    assert reads == []


def test_app_enabled_secret_wins_without_legacy_fallback(tmp_path: Path) -> None:
    preferences, material = provider_preferences(SecretId.TRANSCRIPTION, enabled=True)
    reads: list[SecretRef] = []

    loaded = load_test_configuration(
        ConfigurationUse.RUNTIME,
        preferences=preferences,
        env_file=write_env(tmp_path, {"ASSEMBLYAI_API_KEY": "legacy-secret"}),
        reader=lambda ref: reads.append(ref) or material,
    )

    assert reads == [material.ref]
    assert loaded.transcription is not None
    assert loaded.transcription.api_key == "app-transcription-secret"
    assert source_for(loaded, SettingKey.ASSEMBLYAI_API_KEY) is SettingSource.APP_KEYCHAIN


def test_corrupt_preferences_fail_optional_egress_closed_except_process_override() -> None:
    calls = 0

    def corrupt_preferences():
        raise RuntimeError("secret store parser detail")

    def unexpected_secret(_ref):
        nonlocal calls
        calls += 1
        raise AssertionError("Keychain should not be read")

    blocked = load_configuration(
        ConfigurationUse.RUNTIME,
        env_file=None,
        process_environment={},
        preference_reader=corrupt_preferences,
        secret_reader=unexpected_secret,
    )
    overridden = load_configuration(
        ConfigurationUse.RUNTIME,
        env_file=None,
        process_environment={"ASSEMBLYAI_API_KEY": "process-secret"},
        preference_reader=corrupt_preferences,
        secret_reader=unexpected_secret,
    )

    assert blocked.meetings_dir_path
    assert blocked.transcription is None
    assert overridden.transcription is not None
    issue = issue_for(overridden, Capability.TRANSCRIPTION)
    assert issue.code is ConfigurationIssueCode.PREFERENCES_UNAVAILABLE
    assert issue.blocking is False
    assert calls == 0
    assert "secret store parser detail" not in repr(overridden)


def test_fixed_scopes_read_only_exact_active_generic_refs() -> None:
    preferences, materials = all_provider_preferences()

    for use, expected in (
        (ConfigurationUse.SEARCH, set()),
        (ConfigurationUse.AUTH, set()),
        (ConfigurationUse.SUMMARIZE, {SecretId.NOTES}),
        (
            ConfigurationUse.RUNTIME,
            {SecretId.TRANSCRIPTION, SecretId.BACKUP, SecretId.NOTES},
        ),
    ):
        reads: list[SecretId] = []
        loaded = load_test_configuration(
            use,
            preferences=preferences,
            reader=lambda ref: reads.append(ref.secret_id) or materials[ref.secret_id],
        )
        assert set(reads) == expected
        assert len(reads) == len(expected)
        assert loaded.use is use


def test_scoped_results_match_full_for_every_authoritative_item() -> None:
    process = {
        "MEETINGS_DIR": "/meetings",
        "GOOGLE_CALENDAR_CREDENTIALS_FILE": "calendar.json",
        "GOOGLE_CALENDAR_ID": "primary",
        "KNOWN_SPEAKERS": "{}",
        "ANTHROPIC_API_KEY": "notes-secret",
        "ANTHROPIC_MODEL": "model",
        "SUMMARY_PROMPT_FILE": "prompt.md",
    }
    full = load_test_configuration(ConfigurationUse.RUNTIME, process=process)

    for use in (
        ConfigurationUse.AUTH,
        ConfigurationUse.SEARCH,
        ConfigurationUse.SUMMARIZE,
    ):
        scoped = load_test_configuration(use, process=process)
        for setting in scoped.resolution.settings:
            key = setting.provenance.key
            assert scoped.value_for(key) == full.value_for(key)
            assert setting.provenance == next(
                item for item in full.resolution.provenance if item.key is key
            )
        for capability in scoped.resolution.capabilities:
            assert capability == full.capability_for(capability.capability)


def test_one_hanging_keychain_ref_is_bounded_and_capability_local(monkeypatch) -> None:
    preferences, materials = all_provider_preferences()
    blocker = threading.Event()
    monkeypatch.setattr(configuration_sources, "SECRET_READ_TIMEOUT_SECONDS", 0.001)

    def read(ref: SecretRef):
        if ref.secret_id is SecretId.TRANSCRIPTION:
            blocker.wait()
        return materials[ref.secret_id]

    loaded = load_test_configuration(
        ConfigurationUse.RUNTIME,
        preferences=preferences,
        reader=read,
    )
    blocker.set()

    assert loaded.transcription is None
    assert loaded.backup is not None
    assert loaded.notes is not None
    assert loaded.meetings_dir_path
    issue = issue_for(loaded, Capability.TRANSCRIPTION)
    assert issue.code is ConfigurationIssueCode.SECRET_UNAVAILABLE
    assert issue.blocking is True


def test_generic_keychain_adapter_construction_failure_is_capability_local(
    monkeypatch,
) -> None:
    preferences, _material = provider_preferences(SecretId.TRANSCRIPTION, enabled=True)
    monkeypatch.setattr(
        configuration_sources,
        "KeychainSecretStore",
        lambda: (_ for _ in ()).throw(RuntimeError("backend sentinel")),
    )

    loaded = load_test_configuration(
        ConfigurationUse.RUNTIME,
        preferences=preferences,
        reader=None,
    )

    assert loaded.meetings_dir_path
    assert loaded.transcription is None
    issue = issue_for(loaded, Capability.TRANSCRIPTION)
    assert issue.code is ConfigurationIssueCode.SECRET_UNAVAILABLE
    assert "backend sentinel" not in repr(loaded)


def test_bare_and_wrong_case_env_names_never_enable_transcription(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("ASSEMBLYAI_API_KEY\nassemblyai_api_key=lower\n", encoding="utf-8")

    loaded = load_test_configuration(ConfigurationUse.RUNTIME, env_file=env_file)

    assert loaded.transcription is None
    assert loaded.resolution.value_for(SettingKey.ASSEMBLYAI_API_KEY) == ""


def test_materialization_never_rereads_ambient_sources(monkeypatch) -> None:
    monkeypatch.setenv("MEETINGS_DIR", "/ambient-upper")
    monkeypatch.setenv("meetings_dir", "/ambient-lower")
    monkeypatch.setenv("ASSEMBLYAI_API_KEY", "ambient-secret")

    loaded = load_test_configuration(ConfigurationUse.RUNTIME, process={})

    assert loaded.meetings_dir_path == Path("~/Meetings").expanduser().resolve()
    assert loaded.transcription is None


def test_secret_representations_dumps_and_errors_are_redacted() -> None:
    sentinel = "secret-sentinel"
    preferences, material = provider_preferences(
        SecretId.TRANSCRIPTION,
        enabled=True,
        secret=sentinel,
    )
    loaded = load_test_configuration(
        ConfigurationUse.RUNTIME,
        preferences=preferences,
        reader=lambda _ref: material,
    )

    assert sentinel not in repr(loaded)
    assert sentinel not in repr(loaded.settings)
    assert sentinel not in loaded.settings.model_dump().values()
    assert sentinel not in loaded.settings.model_dump_json()
    assert sentinel not in repr(loaded.transcription)
    with pytest.raises(TypeError):
        asdict(loaded)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        asdict(loaded.transcription)  # type: ignore[arg-type]

    with pytest.raises(ConfigurationLoadError) as error:
        load_test_configuration(
            ConfigurationUse.RUNTIME,
            process={"MAX_RECORDING_MINUTES": sentinel},
        )
    assert sentinel not in str(error.value)


def test_out_of_scope_access_is_rejected() -> None:
    loaded = load_test_configuration(ConfigurationUse.SEARCH)

    with pytest.raises(ValueError, match="outside"):
        loaded.value_for(SettingKey.ANTHROPIC_API_KEY)
    with pytest.raises(ValueError, match="outside"):
        loaded.capability_for(Capability.NOTES)

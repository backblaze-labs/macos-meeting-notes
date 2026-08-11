from pathlib import Path
from types import SimpleNamespace

import pytest

from meeting_memory.config.runtime import RuntimeSettings
from meeting_memory.service.configuration_loader import load_configuration
from meeting_memory.service.runtime_capabilities import RuntimeCapabilityPause
from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration import (
    AppPreferences,
    CapabilityPreference,
    PreferenceSnapshot,
)
from meeting_memory.types.configuration_resolution import ConfigurationUse
from meeting_memory.ui import runtime_app


class Tray:
    controller = None
    ran = False

    def __init__(self, controller, *, readiness_report, configuration_surface=None) -> None:
        assert readiness_report is None
        self.__class__.controller = controller
        self.__class__.configuration_surface = configuration_surface

    def run(self) -> None:
        self.__class__.ran = True


def _loaded(settings: RuntimeSettings) -> SimpleNamespace:
    return SimpleNamespace(
        settings=settings,
        meetings_dir_path=settings.meetings_dir_path,
        transcription=settings.transcription,
        backup=settings.backup,
        calendar=settings.calendar,
        notes=settings.notes,
    )


def test_fresh_profile_starts_normal_core_without_optional_adapters(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = RuntimeSettings(meetings_dir=tmp_path / "meetings")
    Tray.controller = None
    Tray.ran = False
    monkeypatch.setattr(runtime_app, "load_configuration", lambda _use: _loaded(settings))
    monkeypatch.setattr(runtime_app, "RumpsTrayApp", Tray)
    assert not hasattr(runtime_app, "load_readiness_report")
    monkeypatch.setattr(
        runtime_app,
        "AssemblyAITranscriptionClient",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("AssemblyAI built")),
    )
    monkeypatch.setattr(
        runtime_app,
        "B2S3Client",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("B2 built")),
    )
    monkeypatch.setattr(
        runtime_app,
        "GoogleCalendarClient",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Calendar built")),
    )
    monkeypatch.setattr(
        runtime_app,
        "ClaudeSummarizer",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Notes built")),
    )

    assert runtime_app.run_runtime_app() == 0

    assert Tray.ran is True
    assert Tray.controller is not None
    assert Tray.controller.pipeline is None
    assert Tray.controller.committer is not None
    assert Tray.controller.recorder.temp_dir == (
        settings.meetings_dir_path / ".meeting-memory-staging" / "recordings"
    )


def test_optional_constructor_failures_do_not_block_core(
    tmp_path: Path,
    monkeypatch,
) -> None:
    credentials = tmp_path / "calendar.json"
    credentials.write_text("{}", encoding="utf-8")
    settings = RuntimeSettings(
        meetings_dir=tmp_path / "meetings",
        assemblyai_api_key="assembly-key",
        b2_application_key_id="id",
        b2_application_key="key",
        b2_endpoint="https://s3.example.invalid",
        b2_region="region",
        b2_bucket_name="bucket",
        google_calendar_credentials_file=credentials,
        anthropic_api_key="notes-key",
    )
    Tray.ran = False
    monkeypatch.setattr(runtime_app, "load_configuration", lambda _use: _loaded(settings))
    monkeypatch.setattr(runtime_app, "RumpsTrayApp", Tray)

    def fail(*_args, **_kwargs):
        raise RuntimeError("provider constructor failed")

    monkeypatch.setattr(runtime_app, "AssemblyAITranscriptionClient", fail)
    monkeypatch.setattr(runtime_app, "B2S3Client", fail)
    monkeypatch.setattr(runtime_app, "GoogleCalendarClient", fail)
    monkeypatch.setattr(runtime_app, "ClaudeSummarizer", fail)

    assert runtime_app.run_runtime_app() == 0
    assert Tray.ran is True
    assert Tray.controller.committer.policy_provider().transcription is False
    assert Tray.controller.committer.policy_provider().backup is False
    assert Tray.controller.notes_generator is None


def test_runtime_surface_owns_registered_monotonic_pause(tmp_path: Path, monkeypatch) -> None:
    settings = RuntimeSettings(
        meetings_dir=tmp_path / "meetings",
        assemblyai_api_key="assembly-key",
        b2_application_key_id="id",
        b2_application_key="key",
        b2_endpoint="https://s3.example.invalid",
        b2_region="region",
        b2_bucket_name="bucket",
    )
    monkeypatch.setattr(runtime_app, "load_configuration", lambda _use: _loaded(settings))
    monkeypatch.setattr(runtime_app, "RumpsTrayApp", Tray)
    monkeypatch.setattr(runtime_app, "AssemblyAITranscriptionClient", lambda *_a, **_k: object())
    monkeypatch.setattr(runtime_app, "B2S3Client", lambda *_a, **_k: object())

    assert runtime_app.run_runtime_app() == 0

    pause = Tray.configuration_surface._pause  # noqa: SLF001
    assert isinstance(pause, RuntimeCapabilityPause)
    assert Tray.controller.committer.policy_provider().transcription is True
    assert Tray.controller.committer.policy_provider().backup is True
    assert pause.pause(Capability.TRANSCRIPTION)
    assert pause.pause(Capability.BACKUP)
    assert Tray.controller.committer.policy_provider().transcription is False
    assert Tray.controller.committer.policy_provider().backup is False


def test_invalid_optional_settings_never_route_core_to_setup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = RuntimeSettings(
        meetings_dir=tmp_path / "meetings",
        google_calendar_credentials_file=tmp_path / "calendar.json",
        calendar_poll_interval=0,
        anthropic_api_key="notes-key",
        anthropic_model=" ",
    )
    Tray.ran = False
    monkeypatch.setattr(runtime_app, "load_configuration", lambda _use: _loaded(settings))
    monkeypatch.setattr(runtime_app, "RumpsTrayApp", Tray)
    monkeypatch.setattr(
        runtime_app,
        "RumpsSetupApp",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("setup opened")),
    )
    monkeypatch.setattr(
        runtime_app,
        "GoogleCalendarClient",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Calendar built")),
    )
    monkeypatch.setattr(
        runtime_app,
        "ClaudeSummarizer",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Notes built")),
    )

    assert runtime_app.run_runtime_app() == 0
    assert Tray.ran is True
    assert Tray.controller.recorder.temp_dir.is_relative_to(settings.meetings_dir_path)


@pytest.mark.parametrize("preference_state", ["disabled", "corrupt"])
def test_real_composed_fail_closed_configuration_never_constructs_providers(
    tmp_path: Path,
    monkeypatch,
    preference_state: str,
) -> None:
    env_file = tmp_path / ".env"
    credentials = tmp_path / "credentials.json"
    credentials.write_text("{}", encoding="utf-8")
    env_file.write_text(
        "ASSEMBLYAI_API_KEY=legacy-assembly\n"
        "B2_APPLICATION_KEY_ID=legacy-id\n"
        "B2_APPLICATION_KEY=legacy-key\n"
        "B2_ENDPOINT=https://s3.example.invalid\n"
        "B2_REGION=region\n"
        "B2_BUCKET_NAME=bucket\n"
        f"GOOGLE_CALENDAR_CREDENTIALS_FILE={credentials}\n"
        "ANTHROPIC_API_KEY=legacy-notes\n",
        encoding="utf-8",
    )
    if preference_state == "disabled":
        preferences = AppPreferences(
            capabilities=tuple(
                CapabilityPreference(capability, False)
                for capability in Capability
                if capability is not Capability.RECORDING_CORE
            ),
        )

        def preference_reader():
            return PreferenceSnapshot(preferences, None)
    else:

        def preference_reader():
            raise RuntimeError("corrupt")

    loaded = load_configuration(
        ConfigurationUse.RUNTIME,
        env_file=env_file,
        process_environment={"MEETINGS_DIR": str(tmp_path / "meetings")},
        preference_reader=preference_reader,
        secret_reader=lambda _ref: (_ for _ in ()).throw(AssertionError("Keychain read")),
    )
    calls: list[str] = []

    def fail_provider(*_args, **_kwargs):
        calls.append("provider")
        raise AssertionError("provider constructed")

    Tray.ran = False
    monkeypatch.setattr(runtime_app, "load_configuration", lambda _use: loaded)
    monkeypatch.setattr(runtime_app, "configure_logging", lambda: None)
    monkeypatch.setattr(runtime_app, "RumpsTrayApp", Tray)
    monkeypatch.setattr(runtime_app, "AssemblyAITranscriptionClient", fail_provider)
    monkeypatch.setattr(runtime_app, "B2S3Client", fail_provider)
    monkeypatch.setattr(runtime_app, "GoogleCalendarClient", fail_provider)
    monkeypatch.setattr(runtime_app, "ClaudeSummarizer", fail_provider)

    assert runtime_app.run_runtime_app() == 0
    assert Tray.ran is True
    assert Tray.controller.committer is not None
    assert calls == []


def test_explicit_retry_actions_combine_v2_and_isolated_legacy_scanners(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = RuntimeSettings(meetings_dir=tmp_path / "meetings")
    calls: list[str] = []
    jobs = SimpleNamespace(transcription_enabled=True, backup_enabled=True)
    transcription = object()
    backup = object()
    monkeypatch.setattr(
        runtime_app,
        "retry_v2_transcriptions",
        lambda meetings, runtime_jobs: calls.append("v2-transcription"),
    )
    monkeypatch.setattr(
        runtime_app,
        "retry_failed_processing",
        lambda meetings, client, **_kwargs: calls.append("legacy-transcription"),
    )
    monkeypatch.setattr(
        runtime_app,
        "retry_v2_backups",
        lambda meetings, runtime_jobs: calls.append("v2-backup"),
    )
    monkeypatch.setattr(
        runtime_app,
        "sync_pending_meetings",
        lambda meetings, client, **_kwargs: calls.append("legacy-backup"),
    )

    runtime_app._retry_transcriptions(settings, jobs, transcription)
    runtime_app._retry_backups(settings, jobs, backup)

    assert calls == [
        "v2-transcription",
        "legacy-transcription",
        "v2-backup",
        "legacy-backup",
    ]

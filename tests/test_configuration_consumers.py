"""Stage 4B consumer wiring and composed-readiness integration tests."""

from __future__ import annotations

from types import SimpleNamespace

from configuration_loader_fakes import (
    load_test_configuration,
    provider_preferences,
)

from meeting_memory import __main__ as cli
from meeting_memory.config.runtime import CalendarAuthConfig, NotesConfig, RuntimeSettings
from meeting_memory.service import configuration_loader, readiness
from meeting_memory.types.capabilities import Capability, CapabilityState
from meeting_memory.types.configuration import (
    AppPreferences,
    CapabilityPreference,
    SecretId,
)
from meeting_memory.types.configuration_resolution import (
    ConfigurationUse,
)


def test_cli_consumers_request_their_fixed_scopes(tmp_path, monkeypatch) -> None:
    uses: list[ConfigurationUse] = []
    credentials = tmp_path / "credentials.json"
    credentials.write_text("{}", encoding="utf-8")
    meetings = tmp_path / "meetings"
    meetings.mkdir()
    transcript = meetings / "one" / "transcript.md"
    transcript.parent.mkdir()
    transcript.write_text("reviewed", encoding="utf-8")
    loaded_by_use = {
        ConfigurationUse.AUTH: SimpleNamespace(
            calendar_auth=CalendarAuthConfig(credentials, "primary", ()),
        ),
        ConfigurationUse.SEARCH: SimpleNamespace(meetings_dir_path=meetings),
        ConfigurationUse.SUMMARIZE: SimpleNamespace(
            meetings_dir_path=meetings,
            notes=NotesConfig("notes-sentinel", "model", None),
        ),
    }

    def load(use: ConfigurationUse):
        uses.append(use)
        return loaded_by_use[use]

    monkeypatch.setattr(configuration_loader, "load_configuration", load)
    monkeypatch.setattr(
        "meeting_memory.repo.calendar_client.GoogleCalendarClient",
        lambda **_kwargs: SimpleNamespace(authenticate=lambda: None),
    )
    monkeypatch.setattr("meeting_memory.service.search.search_meetings", lambda *_a, **_k: [])
    monkeypatch.setattr(
        "meeting_memory.repo.summarizer.ClaudeSummarizer",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        "meeting_memory.service.runtime_notes.generate_owned_notes",
        lambda *_args: transcript.parent / "notes.md",
    )

    assert cli.run_auth() == 0
    assert cli.run_search("query", limit=1) == 1
    assert cli.run_summarize(transcript) == 0
    assert uses == [
        ConfigurationUse.AUTH,
        ConfigurationUse.SEARCH,
        ConfigurationUse.SUMMARIZE,
    ]


def test_cli_auth_failure_is_sanitized_without_source_path(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    from meeting_memory.repo.calendar_oauth import CalendarAuthorizationError

    credentials = tmp_path / "private-credentials-sentinel.json"
    monkeypatch.setattr(
        configuration_loader,
        "load_configuration",
        lambda _use: SimpleNamespace(calendar_auth=CalendarAuthConfig(credentials, "primary", ())),
    )

    class FailedClient:
        def __init__(self, **_kwargs) -> None:
            pass

        def authenticate(self) -> None:
            raise CalendarAuthorizationError("oauth-secret-sentinel")

    monkeypatch.setattr(
        "meeting_memory.repo.calendar_client.GoogleCalendarClient",
        FailedClient,
    )

    assert cli.run_auth() == 2
    error = capsys.readouterr().err
    assert "authorization failed safely" in error
    assert "private-credentials-sentinel" not in error
    assert "oauth-secret-sentinel" not in error


def test_cli_notes_failure_is_sanitized_and_preserves_local_files(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    transcript = tmp_path / "meeting" / "transcript.md"
    transcript.parent.mkdir()
    transcript.write_text("private transcript sentinel", encoding="utf-8")
    loaded = SimpleNamespace(
        notes=NotesConfig("api-secret-sentinel", "model", tmp_path / "unsafe-prompt"),
        meetings_dir_path=tmp_path,
    )
    monkeypatch.setattr(configuration_loader, "load_configuration", lambda _use: loaded)
    monkeypatch.setattr(
        "meeting_memory.service.runtime_notes.generate_owned_notes",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("api-secret-sentinel")),
    )

    assert cli.run_summarize(transcript) == 2
    error = capsys.readouterr().err
    assert error == "Notes generation failed safely; the transcript is unchanged.\n"
    assert transcript.read_text(encoding="utf-8") == "private transcript sentinel"
    assert not (transcript.parent / "notes.md").exists()


def test_readiness_uses_the_exact_composed_snapshot(monkeypatch) -> None:
    settings = RuntimeSettings(_env_file=None)
    loaded = SimpleNamespace(settings=settings)
    report = object()
    captured: list[object] = []
    monkeypatch.setattr(
        readiness,
        "load_configuration",
        lambda use, **_kwargs: loaded if use is ConfigurationUse.READINESS else None,
    )

    def build(actual, *, configuration, capture_mode):
        captured.extend((actual, configuration, capture_mode))
        return report

    monkeypatch.setattr(readiness, "build_readiness_report", build)

    assert readiness.load_readiness_report() is report
    assert captured == [settings, loaded, "full-meeting"]


def test_composed_readiness_fails_app_errors_closed_but_degrades_override(
    tmp_path,
) -> None:
    def corrupt_preferences():
        raise RuntimeError("private parser detail")

    blocked = configuration_loader.load_configuration(
        ConfigurationUse.READINESS,
        env_file=None,
        process_environment={"MEETINGS_DIR": str(tmp_path / "blocked")},
        preference_reader=corrupt_preferences,
    )
    overridden = configuration_loader.load_configuration(
        ConfigurationUse.READINESS,
        env_file=None,
        process_environment={
            "MEETINGS_DIR": str(tmp_path / "overridden"),
            "ASSEMBLYAI_API_KEY": "process-sentinel",
        },
        preference_reader=corrupt_preferences,
    )

    blocked_report = _report(blocked)
    override_report = _report(overridden)

    assert blocked_report.recording_ready is True
    assert blocked_report.status_for(Capability.TRANSCRIPTION).state is CapabilityState.FAILED
    transcription = override_report.status_for(Capability.TRANSCRIPTION)
    assert transcription.state is CapabilityState.DEGRADED
    assert "process-sentinel" not in f"{transcription.summary} {transcription.action}"


def test_explicit_calendar_disable_short_circuits_oauth_keychain(tmp_path) -> None:
    preferences = AppPreferences(
        capabilities=(CapabilityPreference(Capability.CALENDAR, False),),
    )
    loaded = load_test_configuration(
        ConfigurationUse.READINESS,
        preferences=preferences,
        process={"MEETINGS_DIR": str(tmp_path / "meetings")},
    )
    calls = 0

    def token_reader():
        nonlocal calls
        calls += 1
        raise AssertionError("Google token Keychain must not be read")

    report = _report(loaded, token_reader=token_reader)

    assert report.status_for(Capability.CALENDAR).state is CapabilityState.UNCONFIGURED
    assert calls == 0


def test_generic_keychain_failure_is_capability_local(tmp_path) -> None:
    preferences, _material = provider_preferences(SecretId.TRANSCRIPTION, enabled=True)
    loaded = load_test_configuration(
        ConfigurationUse.READINESS,
        preferences=preferences,
        process={"MEETINGS_DIR": str(tmp_path / "meetings")},
        reader=lambda _ref: None,
    )

    report = _report(loaded)

    assert report.recording_ready is True
    assert report.status_for(Capability.TRANSCRIPTION).state is CapabilityState.FAILED
    assert report.status_for(Capability.BACKUP).state is CapabilityState.UNCONFIGURED


def test_blank_core_path_routes_runtime_and_cli_to_safe_failures(tmp_path, monkeypatch) -> None:
    original_load = configuration_loader.load_configuration

    def load(use: ConfigurationUse):
        return original_load(
            use,
            env_file=None,
            process_environment={"MEETINGS_DIR": ""},
            preference_reader=_empty_snapshot,
        )

    setup = SimpleNamespace(ran=False)

    class SetupApp:
        def __init__(self, *, readiness_report) -> None:
            assert readiness_report is None

        def run(self) -> None:
            setup.ran = True

    monkeypatch.setattr("meeting_memory.ui.runtime_app.load_configuration", load)
    monkeypatch.setattr("meeting_memory.ui.runtime_app.RumpsSetupApp", SetupApp)
    monkeypatch.setattr(configuration_loader, "load_configuration", load)
    monkeypatch.setattr(
        "meeting_memory.service.search.search_meetings",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("search used cwd")),
    )

    from meeting_memory.ui.runtime_app import run_runtime_app

    assert run_runtime_app() == 0
    assert setup.ran is True
    assert cli.run_search("query", limit=1) == 2


def test_blank_core_path_becomes_failed_readiness_without_native_probe(tmp_path) -> None:
    report = readiness.load_readiness_report(
        env_file=None,
        process_environment={"MEETINGS_DIR": ""},
        preference_reader=_empty_snapshot,
    )

    assert report.recording_ready is False
    assert report.status_for(Capability.RECORDING_CORE).state is CapabilityState.FAILED


def _empty_snapshot():
    from meeting_memory.types.configuration import PreferenceSnapshot

    return PreferenceSnapshot(AppPreferences(), None)


def _report(loaded, **kwargs):
    return readiness.build_readiness_report(
        loaded.settings,
        configuration=loaded,
        native_probe=lambda: {
            "event": "supported",
            "microphone": "Built-in",
            "microphone_permission": "authorized",
            "system_audio_permission": "authorized",
        },
        durable_probe=lambda _path: None,
        system_name="Darwin",
        kernel_release="24.0.0",
        python_version=(3, 11),
        **kwargs,
    )

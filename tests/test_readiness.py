"""Capability-scoped readiness builder acceptance tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from meeting_memory.config.runtime import RuntimeSettings
from meeting_memory.service import readiness, recording_readiness
from meeting_memory.types.capabilities import Capability, CapabilityState
from meeting_memory.types.configuration import AppPreferences, PreferenceSnapshot


@pytest.fixture(autouse=True)
def isolate_runtime_environment(monkeypatch, tmp_path: Path) -> None:
    for field_name in RuntimeSettings.model_fields:
        monkeypatch.delenv(field_name, raising=False)
        monkeypatch.delenv(field_name.upper(), raising=False)
    monkeypatch.chdir(tmp_path)


def test_fresh_profile_has_usable_local_core_and_unconfigured_optionals_without_keychain(
    tmp_path: Path,
) -> None:
    token_calls = 0
    _write_desktop_credentials(tmp_path / "credentials.json")

    def unexpected_token_read() -> str | None:
        nonlocal token_calls
        token_calls += 1
        raise AssertionError("Keychain should not be read")

    report = _build(
        RuntimeSettings(_env_file=None, meetings_dir=tmp_path / "meetings"),
        token_reader=unexpected_token_read,
        native_probe=lambda: {
            "event": "supported",
            "microphone": "Built-in",
            "microphone_permission": "not-determined",
            "system_audio_permission": "not-authorized",
        },
    )

    assert report.recording_ready is True
    assert [status.state for status in report.statuses] == [
        CapabilityState.DEGRADED,
        CapabilityState.UNCONFIGURED,
        CapabilityState.UNCONFIGURED,
        CapabilityState.UNCONFIGURED,
        CapabilityState.UNCONFIGURED,
    ]
    assert token_calls == 0
    assert (tmp_path / "meetings").is_dir()
    assert list((tmp_path / "meetings").glob(".meeting-memory-readiness-*")) == []


def test_missing_microphone_degrades_but_keeps_recording_usable(tmp_path: Path) -> None:
    report = _build(
        RuntimeSettings(_env_file=None, meetings_dir=tmp_path / "meetings"),
        native_probe=lambda: {
            "event": "supported",
            "microphone": "none",
            "microphone_permission": "authorized",
            "system_audio_permission": "authorized",
        },
    )

    core = report.status_for(Capability.RECORDING_CORE)
    assert core.state is CapabilityState.DEGRADED
    assert core.usable is True
    assert "a default microphone" in core.summary
    assert "Select a macOS input device" in core.action


def test_authorized_full_meeting_is_ready(tmp_path: Path) -> None:
    core = _build(RuntimeSettings(_env_file=None, meetings_dir=tmp_path / "meetings")).status_for(
        Capability.RECORDING_CORE
    )

    assert core.state is CapabilityState.READY
    assert "Full Meeting permissions are ready" in core.summary
    assert core.action is None


def test_silent_mode_ignores_microphone_permission_and_device(tmp_path: Path) -> None:
    report = _build(
        RuntimeSettings(_env_file=None, meetings_dir=tmp_path / "meetings"),
        capture_mode="silent-system-only",
        native_probe=lambda: {
            "event": "supported",
            "microphone": "none",
            "microphone_permission": "denied",
            "system_audio_permission": "authorized",
        },
    )

    core = report.status_for(Capability.RECORDING_CORE)
    assert core.state is CapabilityState.READY
    assert "Silent System Only permissions are ready" in core.summary


def test_non_directory_meetings_root_fails_only_recording_core(tmp_path: Path) -> None:
    meetings_file = tmp_path / "meetings"
    meetings_file.write_text("not a directory", encoding="utf-8")

    report = _build(RuntimeSettings(_env_file=None, meetings_dir=meetings_file))

    assert report.recording_ready is False
    assert report.status_for(Capability.RECORDING_CORE).state is CapabilityState.FAILED
    assert report.status_for(Capability.TRANSCRIPTION).state is CapabilityState.UNCONFIGURED


def test_optional_groups_are_independent_and_local_problems_are_isolated(
    tmp_path: Path,
) -> None:
    settings = RuntimeSettings(
        _env_file=None,
        meetings_dir=tmp_path / "meetings",
        assemblyai_api_key="assembly-secret",
        b2_application_key_id="id",
        b2_application_key="b2-secret",
        b2_endpoint="not-an-endpoint",
        b2_region="region",
        b2_bucket_name="bucket",
        anthropic_api_key="anthropic-secret",
        anthropic_model=" ",
    )

    report = _build(settings)

    assert report.status_for(Capability.TRANSCRIPTION).state is CapabilityState.READY
    assert report.status_for(Capability.BACKUP).state is CapabilityState.FAILED
    assert report.status_for(Capability.CALENDAR).state is CapabilityState.UNCONFIGURED
    assert report.status_for(Capability.NOTES).state is CapabilityState.FAILED
    visible = " ".join(f"{status.summary} {status.action or ''}" for status in report.statuses)
    assert "assembly-secret" not in visible
    assert "b2-secret" not in visible
    assert "anthropic-secret" not in visible


def test_partial_and_placeholder_backup_groups_are_unconfigured(tmp_path: Path) -> None:
    partial = RuntimeSettings(
        _env_file=None,
        meetings_dir=tmp_path / "meetings",
        b2_application_key_id="id",
    )
    placeholders = RuntimeSettings(
        _env_file=None,
        meetings_dir=tmp_path / "meetings",
        b2_application_key_id="replace-me",
        b2_application_key="replace-me",
        b2_endpoint="replace-me",
        b2_region="replace-me",
        b2_bucket_name="replace-me",
    )

    assert _build(partial).status_for(Capability.BACKUP).state is CapabilityState.UNCONFIGURED
    assert _build(placeholders).status_for(Capability.BACKUP).state is CapabilityState.UNCONFIGURED


def test_calendar_missing_or_invalid_file_short_circuits_keychain(tmp_path: Path) -> None:
    calls = 0

    def token_reader() -> str | None:
        nonlocal calls
        calls += 1
        return "token"

    settings = RuntimeSettings(
        _env_file=None,
        meetings_dir=tmp_path / "meetings",
        google_calendar_credentials_file=tmp_path / "missing.json",
    )
    report = _build(settings, token_reader=token_reader)

    assert report.status_for(Capability.CALENDAR).state is CapabilityState.FAILED
    assert calls == 0


def _valid_token() -> str:
    return json.dumps(
        {
            "refresh_token": "oauth-token",
            "client_id": "client",
            "client_secret": "secret",
        }
    )


@pytest.mark.parametrize(
    ("token_reader", "state"),
    [
        (lambda: None, CapabilityState.FAILED),
        (_valid_token, CapabilityState.READY),
        (lambda: json.dumps({"refresh_token": "oauth-token"}), CapabilityState.FAILED),
        (lambda: "not-json", CapabilityState.FAILED),
        (
            lambda: (_ for _ in ()).throw(RuntimeError("secret backend detail")),
            CapabilityState.FAILED,
        ),
    ],
)
def test_calendar_token_outcomes_are_capability_local_and_sanitized(
    tmp_path: Path,
    token_reader,
    state: CapabilityState,
) -> None:
    credentials = tmp_path / "credentials.json"
    _write_desktop_credentials(credentials)
    settings = RuntimeSettings(
        _env_file=None,
        meetings_dir=tmp_path / "meetings",
        google_calendar_credentials_file=credentials,
    )

    report = _build(settings, token_reader=token_reader)

    calendar = report.status_for(Capability.CALENDAR)
    assert calendar.state is state
    assert "secret backend detail" not in calendar.summary
    assert report.recording_ready is True


def test_legacy_env_is_unchanged_and_process_environment_keeps_precedence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    env_file = tmp_path / ".env"
    original = b"MEETINGS_DIR=./meetings\nASSEMBLYAI_API_KEY=replace-me\nB2_ENDPOINT=not-valid\n"
    env_file.write_bytes(original)
    monkeypatch.setenv("ASSEMBLYAI_API_KEY", "process-secret")
    monkeypatch.setattr(recording_readiness.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(recording_readiness.platform, "release", lambda: "24.0.0")
    monkeypatch.setattr(
        recording_readiness,
        "check_native_capture",
        _ready_native_event,
    )

    report = readiness.load_readiness_report(
        env_file,
        preference_reader=lambda: PreferenceSnapshot(AppPreferences(), None),
    )

    assert report.status_for(Capability.TRANSCRIPTION).state is CapabilityState.READY
    assert report.status_for(Capability.BACKUP).state is CapabilityState.UNCONFIGURED
    assert env_file.read_bytes() == original
    rendered = " ".join(status.summary for status in report.statuses)
    assert "process-secret" not in rendered


def _build(settings: RuntimeSettings, **kwargs):
    kwargs.setdefault("native_probe", _ready_native_event)
    kwargs.setdefault("system_name", "Darwin")
    kwargs.setdefault("kernel_release", "24.0.0")
    kwargs.setdefault("python_version", (3, 11))
    return readiness.build_readiness_report(settings, **kwargs)


def _ready_native_event() -> dict[str, str]:
    return {
        "event": "supported",
        "microphone": "Built-in",
        "microphone_permission": "authorized",
        "system_audio_permission": "authorized",
    }


def _write_desktop_credentials(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "installed": {
                    "client_id": "client",
                    "client_secret": "secret",
                    "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": ["http://localhost"],
                }
            }
        ),
        encoding="utf-8",
    )

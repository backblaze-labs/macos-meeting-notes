"""Adversarial readiness I/O and timeout tests."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from meeting_memory.config.runtime import RuntimeSettings
from meeting_memory.service import readiness, readiness_integrations
from meeting_memory.types.capabilities import Capability, CapabilityState


@pytest.fixture(autouse=True)
def isolate_runtime_environment(monkeypatch, tmp_path: Path) -> None:
    for field_name in RuntimeSettings.model_fields:
        monkeypatch.delenv(field_name, raising=False)
        monkeypatch.delenv(field_name.upper(), raising=False)
    monkeypatch.chdir(tmp_path)


@pytest.mark.parametrize("operation", ["write", "fsync"])
def test_durable_storage_probe_failures_keep_core_unusable_and_clean_up(
    tmp_path: Path,
    operation: str,
) -> None:
    meetings_dir = tmp_path / "meetings"

    def fail(*_args, **_kwargs):
        raise OSError(f"{operation} backend detail")

    def durable_probe(path: Path) -> None:
        if operation == "write":
            readiness._probe_durable_write(path, writer=fail)
        else:
            readiness._probe_durable_write(path, sync=fail)

    report = _build(
        RuntimeSettings(_env_file=None, meetings_dir=meetings_dir),
        durable_probe=durable_probe,
    )

    core = report.status_for(Capability.RECORDING_CORE)
    assert core.state is CapabilityState.FAILED
    assert f"{operation} backend detail" not in core.summary
    assert list(meetings_dir.glob(".meeting-memory-readiness-*")) == []


@pytest.mark.parametrize("error", [OSError("launch failed"), TimeoutError("timed out")])
def test_unexpected_native_probe_errors_become_sanitized_core_failure(
    tmp_path: Path,
    error: Exception,
) -> None:
    def fail_probe():
        raise error

    report = _build(
        RuntimeSettings(_env_file=None, meetings_dir=tmp_path / "meetings"),
        native_probe=fail_probe,
    )

    core = report.status_for(Capability.RECORDING_CORE)
    assert core.state is CapabilityState.FAILED
    assert "launch failed" not in core.summary
    assert "timed out" not in core.summary


def test_calendar_keychain_check_is_bounded(tmp_path: Path, monkeypatch) -> None:
    credentials = tmp_path / "credentials.json"
    _write_desktop_credentials(credentials)
    settings = RuntimeSettings(
        _env_file=None,
        meetings_dir=tmp_path / "meetings",
        google_calendar_credentials_file=credentials,
    )
    monkeypatch.setattr(readiness_integrations, "KEYCHAIN_TIMEOUT_SECONDS", 0.001)
    blocker = threading.Event()

    report = _build(settings, token_reader=lambda: blocker.wait() or None)
    blocker.set()

    calendar = report.status_for(Capability.CALENDAR)
    assert calendar.state is CapabilityState.FAILED
    assert "Keychain" in calendar.summary


@pytest.mark.parametrize("kind", ["fifo", "oversize"])
def test_calendar_rejects_nonregular_or_oversize_credentials_before_keychain(
    tmp_path: Path,
    monkeypatch,
    kind: str,
) -> None:
    credentials = tmp_path / "credentials.json"
    if kind == "fifo":
        readiness_integrations.os.mkfifo(credentials)
    else:
        credentials.write_bytes(b"x" * (readiness_integrations.MAX_LOCAL_CONFIG_BYTES + 1))
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unbounded read")),
    )
    token_calls = 0

    def token_reader() -> str:
        nonlocal token_calls
        token_calls += 1
        return _valid_token()

    settings = RuntimeSettings(
        _env_file=None,
        meetings_dir=tmp_path / "meetings",
        google_calendar_credentials_file=credentials,
    )

    report = _build(settings, token_reader=token_reader)

    assert report.status_for(Capability.CALENDAR).state is CapabilityState.FAILED
    assert token_calls == 0


def test_notes_degrades_for_oversize_prompt_without_reading_it(tmp_path: Path) -> None:
    prompt = tmp_path / "prompt.md"
    prompt.write_bytes(b"x" * (readiness_integrations.MAX_LOCAL_CONFIG_BYTES + 1))
    settings = RuntimeSettings(
        _env_file=None,
        meetings_dir=tmp_path / "meetings",
        anthropic_api_key="anthropic-secret",
        summary_prompt_file=prompt,
    )

    report = _build(settings)

    notes = report.status_for(Capability.NOTES)
    assert notes.state is CapabilityState.DEGRADED
    assert notes.action


def _build(settings: RuntimeSettings, **kwargs):
    kwargs.setdefault(
        "native_probe", lambda: {"event": "supported", "microphone": "Built-in"}
    )
    kwargs.setdefault("system_name", "Darwin")
    kwargs.setdefault("kernel_release", "24.0.0")
    kwargs.setdefault("python_version", (3, 11))
    return readiness.build_readiness_report(settings, **kwargs)


def _write_desktop_credentials(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "installed": {
                    "client_id": "client",
                    "client_secret": "secret",
                    "auth_uri": "https://accounts.example/auth",
                    "token_uri": "https://accounts.example/token",
                }
            }
        ),
        encoding="utf-8",
    )


def _valid_token() -> str:
    return json.dumps(
        {
            "refresh_token": "oauth-token",
            "client_id": "client",
            "client_secret": "secret",
        }
    )

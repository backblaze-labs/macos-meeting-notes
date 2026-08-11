"""Adversarial readiness I/O and timeout tests."""

from __future__ import annotations

import json
import os
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


@pytest.mark.parametrize("kind", ["symlink", "fifo", "oversize", "foreign", "duplicate"])
def test_calendar_rejects_nonregular_or_oversize_credentials_before_keychain(
    tmp_path: Path,
    monkeypatch,
    kind: str,
) -> None:
    credentials = tmp_path / "credentials.json"
    if kind == "symlink":
        target = tmp_path / "target.json"
        _write_desktop_credentials(target)
        credentials.symlink_to(target)
    elif kind == "fifo":
        os.mkfifo(credentials)
    elif kind == "oversize":
        credentials.write_bytes(b"x" * (readiness_integrations.MAX_LOCAL_CONFIG_BYTES + 1))
    elif kind == "foreign":
        payload = _desktop_credentials()
        payload["installed"]["auth_uri"] = "https://accounts.google.com/foreign"
        credentials.write_text(json.dumps(payload), encoding="utf-8")
    else:
        credentials.write_text(
            '{"installed":{"client_id":"one","client_id":"two"}}',
            encoding="utf-8",
        )
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


def test_notes_fails_for_oversize_prompt_without_reading_it(tmp_path: Path) -> None:
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
    assert notes.state is CapabilityState.FAILED
    assert notes.action


@pytest.mark.parametrize("kind", ["symlink", "intermediate", "fifo", "invalid_utf8"])
def test_notes_readiness_matches_runtime_prompt_source_rejections(
    tmp_path: Path,
    kind: str,
) -> None:
    prompt = tmp_path / "prompt.md"
    if kind == "symlink":
        target = tmp_path / "target.md"
        target.write_text("private", encoding="utf-8")
        prompt.symlink_to(target)
    elif kind == "intermediate":
        target = tmp_path / "target"
        target.mkdir()
        (target / "prompt.md").write_text("private", encoding="utf-8")
        parent = tmp_path / "linked"
        parent.symlink_to(target, target_is_directory=True)
        prompt = parent / "prompt.md"
    elif kind == "fifo":
        os.mkfifo(prompt)
    else:
        prompt.write_bytes(b"\xff")
    settings = RuntimeSettings(
        _env_file=None,
        meetings_dir=tmp_path / "meetings",
        anthropic_api_key="anthropic-secret",
        summary_prompt_file=prompt,
    )

    status = _build(settings).status_for(Capability.NOTES)

    assert status.state is CapabilityState.FAILED
    assert "anthropic-secret" not in f"{status.summary} {status.action}"


def test_notes_readiness_rejects_prompt_mutated_during_read(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from meeting_memory.repo import prompt_source

    prompt = tmp_path / "prompt.md"
    prompt.write_text("original", encoding="utf-8")
    original_read = prompt_source.os.read
    mutated = False

    def mutate_after_read(descriptor: int, size: int) -> bytes:
        nonlocal mutated
        content = original_read(descriptor, size)
        if content and not mutated:
            mutated = True
            prompt.write_text("changed", encoding="utf-8")
        return content

    monkeypatch.setattr(prompt_source.os, "read", mutate_after_read)
    settings = RuntimeSettings(
        _env_file=None,
        meetings_dir=tmp_path / "meetings",
        anthropic_api_key="anthropic-secret",
        summary_prompt_file=prompt,
    )

    assert _build(settings).status_for(Capability.NOTES).state is CapabilityState.FAILED


@pytest.mark.parametrize(
    "token",
    [
        '{"refresh_token":"one","refresh_token":"two","client_id":"id","client_secret":"secret"}',
        json.dumps(
            {
                "refresh_token": "token",
                "client_id": "id",
                "client_secret": "secret",
                "token_uri": "https://oauth2.googleapis.com/foreign",
            }
        ),
        "x" * (readiness_integrations.MAX_LOCAL_CONFIG_BYTES + 1),
    ],
)
def test_calendar_readiness_rejects_tokens_explicit_auth_would_not_persist(
    tmp_path: Path,
    token: str,
) -> None:
    credentials = tmp_path / "credentials.json"
    _write_desktop_credentials(credentials)
    settings = RuntimeSettings(
        _env_file=None,
        meetings_dir=tmp_path / "meetings",
        google_calendar_credentials_file=credentials,
    )

    status = _build(settings, token_reader=lambda: token).status_for(Capability.CALENDAR)

    assert status.state is CapabilityState.FAILED
    assert "secret" not in status.summary.casefold()


def _build(settings: RuntimeSettings, **kwargs):
    kwargs.setdefault("native_probe", lambda: {"event": "supported", "microphone": "Built-in"})
    kwargs.setdefault("system_name", "Darwin")
    kwargs.setdefault("kernel_release", "24.0.0")
    kwargs.setdefault("python_version", (3, 11))
    return readiness.build_readiness_report(settings, **kwargs)


def _write_desktop_credentials(path: Path) -> None:
    path.write_text(json.dumps(_desktop_credentials()), encoding="utf-8")


def _desktop_credentials() -> dict[str, dict[str, object]]:
    return {
        "installed": {
            "client_id": "client",
            "client_secret": "secret",
            "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }


def _valid_token() -> str:
    return json.dumps(
        {
            "refresh_token": "oauth-token",
            "client_id": "client",
            "client_secret": "secret",
        }
    )

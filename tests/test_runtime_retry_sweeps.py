"""Runtime sweeps preserve explicit legacy and schema-v2 retry behavior."""

from pathlib import Path
from types import SimpleNamespace

from meeting_memory.config.runtime import RuntimeSettings
from meeting_memory.service import runtime_retry_sweeps
from meeting_memory.ui import runtime_app


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
        runtime_retry_sweeps,
        "retry_v2_transcriptions",
        lambda meetings, runtime_jobs: calls.append("v2-transcription"),
    )
    monkeypatch.setattr(
        runtime_retry_sweeps,
        "retry_failed_processing",
        lambda meetings, client, **_kwargs: calls.append("legacy-transcription"),
    )
    monkeypatch.setattr(
        runtime_retry_sweeps,
        "retry_v2_backups",
        lambda meetings, runtime_jobs: calls.append("v2-backup"),
    )
    monkeypatch.setattr(
        runtime_retry_sweeps,
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

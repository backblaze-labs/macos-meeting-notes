"""Structural guards that keep Stage 4C dormant until native consent in 4D."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "meeting_memory"


def test_migration_engine_has_no_active_consumer_imports() -> None:
    allowed = {
        "types/configuration_migration.py",
        "service/configuration_migration.py",
        "service/configuration_migration_cas.py",
        "service/configuration_migration_outcomes.py",
        "service/configuration_migration_plan.py",
        "service/configuration_migration_source.py",
        "service/configuration_migration_state.py",
    }
    violations = [
        str(path.relative_to(SOURCE))
        for path in SOURCE.rglob("*.py")
        if str(path.relative_to(SOURCE)) not in allowed
        and "configuration_migration" in path.read_text(encoding="utf-8")
    ]

    assert violations == []


def test_migration_engine_has_no_env_mutation_save_provider_or_event_boundary() -> None:
    service_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (SOURCE / "service").glob("configuration_migration*.py")
    )

    for forbidden in (
        "write_text(",
        "write_bytes(",
        "os.unlink(",
        ".save(",
        "types.events",
        "calendar_client",
        "boto3",
        "assemblyai",
        "anthropic",
    ):
        assert forbidden not in service_sources

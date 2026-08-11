"""Structural guards for the explicit Stage 4D migration surface."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "meeting_memory"


def test_migration_engine_is_reachable_only_through_explicit_configuration_surface() -> None:
    allowed = {
        "types/configuration_migration.py",
        "service/configuration_migration.py",
        "service/configuration_migration_cas.py",
        "service/configuration_migration_outcomes.py",
        "service/configuration_migration_plan.py",
        "service/configuration_migration_source.py",
        "service/configuration_migration_state.py",
        "types/configuration_surface.py",
        "service/configuration_surface.py",
        "service/configuration_surface_operations.py",
        "ui/configuration_surface.py",
        "ui/migration_form.py",
    }
    violations = [
        str(path.relative_to(SOURCE))
        for path in SOURCE.rglob("*.py")
        if str(path.relative_to(SOURCE)) not in allowed
        and "configuration_migration" in path.read_text(encoding="utf-8")
    ]

    assert violations == []
    assert "configuration_migration" in (SOURCE / "service" / "configuration_surface.py").read_text(
        encoding="utf-8"
    )


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

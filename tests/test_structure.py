"""Mechanical repository structure checks."""

from __future__ import annotations

import ast
from pathlib import Path

import structure_distribution_files as distribution
from structure_d2_files import REQUIRED_D2_SOURCE_FILES
from structure_native_files import REQUIRED_NATIVE_SOURCE_FILES

ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src" / "meeting_memory"
TESTS_ROOT = ROOT / "tests"

LAYERS = {"types": 0, "config": 1, "repo": 2, "service": 3, "ui": 4}

EXTERNAL_SDK_PREFIXES = (
    "anthropic",
    "assemblyai",
    "boto3",
    "botocore",
    "google",
    "google_auth_oauthlib",
    "googleapiclient",
    "google_auth_httplib2",
    "httplib2",
    "keyring",
)

REQUIRED_SOURCE_FILES = (
    *REQUIRED_D2_SOURCE_FILES,
    *distribution.REQUIRED_DISTRIBUTION_SOURCE_FILES,
    "__init__.py",
    "__main__.py",
    "doctor.py",
    "logging_config.py",
    "types/__init__.py",
    "types/capabilities.py",
    "types/configuration.py",
    "types/configuration_editing.py",
    "types/configuration_migration.py",
    "types/configuration_resolution.py",
    "types/calendar_authorization.py",
    "types/artifacts.py",
    "types/backup.py",
    "types/meeting.py",
    "types/transcript.py",
    "types/summary.py",
    "types/events.py",
    "types/egress.py",
    "types/recovery.py",
    "types/speakers.py",
    "config/__init__.py",
    "config/settings.py",
    "config/runtime.py",
    "config/schema.py",
    "config/validation.py",
    "config/resolution.py",
    "config/secret_payloads.py",
    "repo/__init__.py",
    "repo/b2_client.py",
    "repo/b2_snapshot.py",
    "repo/pinned_path.py",
    "repo/retry.py",
    "repo/prompt_source.py",
    "repo/transcription.py",
    "repo/summarizer.py",
    "repo/calendar_client.py",
    "repo/calendar_oauth.py",
    "repo/secret_store.py",
    "repo/google_http.py",
    "repo/native_audio.py",
    "repo/native_audio_validation.py",
    "service/__init__.py",
    "service/storage.py",
    "service/stage_integrity.py",
    "service/atomic_io.py",
    "service/meeting_locks.py",
    "service/meeting_document.py",
    "service/meeting_paths.py",
    "service/meeting_store.py",
    "service/file_snapshot.py",
    "service/pinned_fs.py",
    "service/recovery_index.py",
    "service/legacy_recovery_index.py",
    "service/recovery_cleanup.py",
    "service/recovery_audio.py",
    "service/recovery_commit.py",
    "service/recovery_journal.py",
    "service/recovery_marker.py",
    "service/recovery_provenance.py",
    "service/recovery_quarantine.py",
    "service/recovery_outcomes.py",
    "service/recovery_publication.py",
    "service/meeting_state.py",
    "service/meeting_state_fields.py",
    "service/transcript_state.py",
    "service/speaker_state.py",
    "service/ownership.py",
    "service/backup_revision.py",
    "service/backup_snapshot_fs.py",
    "service/markdown.py",
    "service/recorder.py",
    "service/local_commit.py",
    "service/runtime_backup_gate.py",
    "service/runtime_capabilities.py",
    "service/runtime_jobs.py",
    "service/runtime_legacy_recovery.py",
    "service/recovery_reconcile.py",
    "service/runtime_transcription.py",
    "service/runtime_files.py",
    "service/transcription_audio.py",
    "service/legacy_snapshot.py",
    "service/runtime_notes.py",
    "service/runtime_notes_gate.py",
    "service/runtime_retry.py",
    "service/readiness.py",
    "service/recording_readiness.py",
    "service/readiness_configuration.py",
    "service/readiness_integrations.py",
    "service/configuration_loader.py",
    "service/configuration_editing.py",
    "service/configuration_editing_cas.py",
    "service/configuration_editing_outcomes.py",
    "service/configuration_editing_support.py",
    "service/configuration_migration.py",
    "service/configuration_migration_cas.py",
    "service/configuration_migration_outcomes.py",
    "service/configuration_migration_plan.py",
    "service/configuration_migration_source.py",
    "service/configuration_migration_state.py",
    "service/configuration_loaded.py",
    "service/configuration_issues.py",
    "service/configuration_sources.py",
    "service/preference_store.py",
    "service/preference_store_fs.py",
    "service/audio_modes.py",
    "service/native_audio_setup.py",
    "service/summary_prompt.py",
    "service/pipeline.py",
    "service/calendar_watcher.py",
    "service/calendar_authorization.py",
    "service/sync.py",
    "ui/__init__.py",
    "ui/tray.py",
    "ui/menu.py",
    "ui/audio_modes.py",
    "ui/notes_prompt.py",
    "ui/processing_launch.py",
    "ui/legacy_processing.py",
    "ui/recovery_actions.py",
    "ui/runtime_events.py",
    "ui/setup_readiness.py",
    "ui/runtime_app.py",
    "ui/recording_health.py",
    "ui/recording_transitions.py",
    "ui/submenus.py",
    "ui/preferences.py",
    "ui/preference_forms.py",
)

REQUIRED_REPO_FILES = (
    *distribution.REQUIRED_DISTRIBUTION_REPO_FILES,
    "AGENTS.md",
    "CLAUDE.md",
    "ARCHITECTURE.md",
    "Makefile",
    "README.md",
    "pyproject.toml",
    "requirements.txt",
    ".env.example",
    ".gitignore",
    "docs/blackhole-setup.md",
    "docs/google-calendar-auth.md",
    "docs/local-first-contract.md",
    "docs/dev-workflows.md",
    "docs/features/_template.md",
    "scripts/doctor.py",
    ".github/workflows/ci.yml",
)


def python_files() -> list[Path]:
    return sorted([*SRC_ROOT.rglob("*.py"), *TESTS_ROOT.rglob("*.py")])


def source_files() -> list[Path]:
    return sorted([*python_files(), *SRC_ROOT.rglob("*.swift")])


def parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def source_layer(path: Path) -> str | None:
    relative = path.relative_to(SRC_ROOT)
    first_part = relative.parts[0]
    return first_part if first_part in LAYERS else None


def imported_modules(tree: ast.Module, path: Path) -> list[str]:
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.extend(import_from_modules(node, path))
    return imports


def import_from_modules(node: ast.ImportFrom, path: Path) -> list[str]:
    if node.level == 0:
        return [node.module] if node.module else []

    package = current_package(path)
    base = package[: len(package) - node.level + 1]
    if node.module:
        return [".".join([*base, *node.module.split(".")])]
    return [".".join([*base, alias.name]) for alias in node.names]


def current_package(path: Path) -> list[str]:
    relative = path.relative_to(SRC_ROOT)
    return ["meeting_memory", *relative.parts[:-1]]


def imported_layer(module_name: str) -> str | None:
    parts = module_name.split(".")
    if len(parts) < 2 or parts[0] != "meeting_memory":
        return None
    return parts[1] if parts[1] in LAYERS else None


def is_external_sdk(module_name: str) -> bool:
    return any(
        module_name == prefix or module_name.startswith(f"{prefix}.")
        for prefix in EXTERNAL_SDK_PREFIXES
    )


def test_no_backward_imports() -> None:
    violations: list[str] = []
    for path in SRC_ROOT.rglob("*.py"):
        layer = source_layer(path)
        if layer is None:
            continue
        for module_name in imported_modules(parse(path), path):
            target_layer = imported_layer(module_name)
            if target_layer and LAYERS[target_layer] > LAYERS[layer]:
                violations.append(f"{path.relative_to(ROOT)} imports {module_name}")

    assert violations == []


def test_external_sdks_only_in_repo() -> None:
    violations: list[str] = []
    for path in SRC_ROOT.rglob("*.py"):
        layer = source_layer(path)
        if layer == "repo":
            continue
        for module_name in imported_modules(parse(path), path):
            if is_external_sdk(module_name):
                violations.append(f"{path.relative_to(ROOT)} imports {module_name}")

    assert violations == []


def test_rumps_only_in_ui() -> None:
    violations: list[str] = []
    for path in SRC_ROOT.rglob("*.py"):
        layer = source_layer(path)
        if layer == "ui":
            continue
        for module_name in imported_modules(parse(path), path):
            if module_name == "rumps" or module_name.startswith("rumps."):
                violations.append(f"{path.relative_to(ROOT)} imports {module_name}")

    assert violations == []


def test_file_size_limits() -> None:
    oversized = [
        f"{path.relative_to(ROOT)} has {len(path.read_text(encoding='utf-8').splitlines())} lines"
        for path in source_files()
        if len(path.read_text(encoding="utf-8").splitlines()) > 300
    ]
    assert oversized == []


def test_required_modules_exist() -> None:
    missing_source = [path for path in REQUIRED_SOURCE_FILES if not (SRC_ROOT / path).exists()]
    missing_native = [
        path for path in REQUIRED_NATIVE_SOURCE_FILES if not (SRC_ROOT / path).exists()
    ]
    missing_repo = [path for path in REQUIRED_REPO_FILES if not (ROOT / path).exists()]

    assert missing_source == []
    assert missing_native == []
    assert missing_repo == []

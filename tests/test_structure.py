"""Mechanical repository structure checks."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src" / "meeting_memory"
TESTS_ROOT = ROOT / "tests"

LAYERS = {
    "types": 0,
    "config": 1,
    "repo": 2,
    "service": 3,
    "ui": 4,
}

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
    "__init__.py",
    "__main__.py",
    "doctor.py",
    "logging_config.py",
    "types/__init__.py",
    "types/capabilities.py",
    "types/artifacts.py",
    "types/meeting.py",
    "types/transcript.py",
    "types/summary.py",
    "types/events.py",
    "types/speakers.py",
    "config/__init__.py",
    "config/settings.py",
    "repo/__init__.py",
    "repo/b2_client.py",
    "repo/retry.py",
    "repo/transcription.py",
    "repo/summarizer.py",
    "repo/calendar_client.py",
    "repo/google_http.py",
    "repo/native_audio.py",
    "service/__init__.py",
    "service/storage.py",
    "service/atomic_io.py",
    "service/meeting_locks.py",
    "service/meeting_paths.py",
    "service/meeting_store.py",
    "service/meeting_state.py",
    "service/meeting_state_fields.py",
    "service/ownership.py",
    "service/backup_revision.py",
    "service/markdown.py",
    "service/recorder.py",
    "service/audio_modes.py",
    "service/native_audio_setup.py",
    "service/summary_prompt.py",
    "service/pipeline.py",
    "service/calendar_watcher.py",
    "service/sync.py",
    "ui/__init__.py",
    "ui/tray.py",
    "ui/menu.py",
    "ui/audio_modes.py",
    "ui/notes_prompt.py",
    "ui/processing_launch.py",
    "ui/recording_health.py",
    "ui/recording_transitions.py",
    "ui/submenus.py",
    "ui/preferences.py",
    "ui/preference_forms.py",
)

REQUIRED_REPO_FILES = (
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

REQUIRED_NATIVE_SOURCE_FILES = (
    "repo/native/CLI.swift",
    "repo/native/NativeCapture.swift",
    "repo/native/ScreenCaptureRecorder.swift",
    "repo/native/SilentSystemRecorder.swift",
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

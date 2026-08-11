"""Runtime consumers share one captured layout instead of ambient cwd."""

from __future__ import annotations

from pathlib import Path

import pytest
from configuration_migration_fakes import FakePreferenceStore, FakeSecretStore

from meeting_memory.config import runtime_layout as runtime_layout_module
from meeting_memory.repo.native_layout import (
    HELPER_ENV_VAR,
    resolve_native_capture_helper,
)
from meeting_memory.repo.pinned_path import open_parent_directory
from meeting_memory.service.configuration_editing_support import editing_legacy_source
from meeting_memory.service.configuration_migration import EnvironmentMigrationService
from meeting_memory.service.pinned_fs import open_directory_tree
from meeting_memory.types.artifacts import BackupSnapshotUpload
from meeting_memory.types.configuration_migration import MigrationPreviewState
from meeting_memory.types.runtime_layout import RuntimeLayout


def test_frozen_layout_is_captured_from_executable_once(tmp_path: Path, monkeypatch) -> None:
    bundle = tmp_path / "Meeting Memory.app"
    executable = bundle / "Contents/MacOS/Meeting Memory"
    monkeypatch.setattr(runtime_layout_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(runtime_layout_module.sys, "executable", str(executable))
    runtime_layout_module.current_runtime_layout.cache_clear()

    first = runtime_layout_module.current_runtime_layout()
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    monkeypatch.chdir(foreign)
    second = runtime_layout_module.current_runtime_layout()

    assert first is second
    assert first.bundle_root == bundle
    assert first.legacy_env_path is None
    runtime_layout_module.current_runtime_layout.cache_clear()


def test_bundled_native_helper_ignores_environment_override(tmp_path: Path) -> None:
    bundle = tmp_path / "Meeting Memory.app"
    helper = bundle / "Contents/MacOS/MeetingMemoryCapture"
    helper.parent.mkdir(parents=True)
    helper.write_bytes(b"helper")
    helper.chmod(0o755)
    foreign = tmp_path / "foreign-helper"
    foreign.write_bytes(b"foreign")
    foreign.chmod(0o755)
    layout = RuntimeLayout.bundled(bundle, home=tmp_path / "home")

    resolved = resolve_native_capture_helper(
        layout,
        environment={HELPER_ENV_VAR: str(foreign)},
    )

    assert resolved == helper


def test_development_native_helper_override_uses_captured_checkout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "checkout"
    helper = project / "tools" / "MeetingMemoryCapture"
    helper.parent.mkdir(parents=True)
    helper.write_bytes(b"helper")
    helper.chmod(0o755)
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    monkeypatch.chdir(foreign)
    layout = RuntimeLayout.development(project, home=tmp_path / "home")

    assert (
        resolve_native_capture_helper(
            layout,
            environment={HELPER_ENV_VAR: "tools/MeetingMemoryCapture"},
        )
        == helper
    )


def test_bundled_editing_and_migration_do_not_scan_cwd(tmp_path: Path) -> None:
    bundle = tmp_path / "Meeting Memory.app"
    layout = RuntimeLayout.bundled(bundle, home=tmp_path / "home")
    source = tmp_path / "selected.env"
    source.write_text("MEETINGS_DIR=meetings\n", encoding="utf-8")
    service = EnvironmentMigrationService(
        preference_store=FakePreferenceStore(),
        secret_store=FakeSecretStore(),
        id_factory=lambda: "a" * 32,
        runtime_layout=layout,
    )

    assert editing_legacy_source(".env", layout) is None
    assert service.requires_source_selection is True
    assert service.preview(process_environment={}).state is MigrationPreviewState.FAILED
    assert (
        service.preview(
            process_environment={},
            source_path=source,
        ).state
        is MigrationPreviewState.READY
    )


def test_pinned_io_boundaries_reject_relative_paths() -> None:
    with pytest.raises(ValueError, match="absolute"):
        open_parent_directory(Path("relative/source"))
    with pytest.raises(ValueError, match="absolute"):
        open_directory_tree(Path("relative/directory"))
    with pytest.raises(ValueError, match="absolute"):
        BackupSnapshotUpload(
            "2026-08-11_12-00_test",
            "0" * 64,
            Path("relative/meeting"),
            1,
            1,
        )

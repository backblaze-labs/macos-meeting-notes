"""Frozen self-check remains value-free and read-only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from meeting_memory.service.bundle_self_check import (
    BUNDLE_SELF_CHECK_EXIT_CODES,
    REQUIRED_IMPORTS,
    RESOURCE_PATHS,
    BundleSelfCheckError,
    inspect_bundle,
    run_bundle_self_check,
)
from meeting_memory.types.runtime_layout import RuntimeLayout
from meeting_memory.version import APP_VERSION


def _bundle(tmp_path: Path) -> tuple[RuntimeLayout, Path]:
    bundle = tmp_path / "Meeting Memory.app"
    layout = RuntimeLayout.bundled(bundle, home=tmp_path / "home")
    helper = layout.native_helper_path
    helper.parent.mkdir(parents=True)
    helper.write_bytes(b"helper")
    helper.chmod(0o755)
    encoder = layout.native_encoder_path
    encoder.write_bytes(b"encoder")
    encoder.chmod(0o755)
    for relative in RESOURCE_PATHS:
        resource = layout.resources_path / relative
        resource.parent.mkdir(parents=True, exist_ok=True)
        resource.write_bytes(b"resource")
    return layout, bundle


def test_bundle_self_check_imports_allowlist_and_reports_no_paths(tmp_path: Path) -> None:
    layout, bundle = _bundle(tmp_path)
    imported: list[str] = []

    report = inspect_bundle(layout, importer=lambda name: imported.append(name))
    rendered = report.render()
    payload = json.loads(rendered)

    assert imported == list(REQUIRED_IMPORTS)
    assert payload == {
        "event": "bundle-self-check",
        "imports_checked": len(REQUIRED_IMPORTS),
        "ready": True,
        "resources_checked": len(RESOURCE_PATHS),
        "version": APP_VERSION,
    }
    assert str(bundle) not in rendered
    assert str(layout.home) not in rendered


def test_bundle_self_check_rejects_missing_resource_before_imports(tmp_path: Path) -> None:
    layout, _bundle_path = _bundle(tmp_path)
    (layout.resources_path / RESOURCE_PATHS[0]).unlink()
    imported: list[str] = []

    with pytest.raises(BundleSelfCheckError, match="required bundled resource") as raised:
        inspect_bundle(layout, importer=lambda name: imported.append(name))

    assert raised.value.stage == "resource-0"
    assert imported == []


def test_bundle_self_check_requires_the_sibling_encoder_before_imports(
    tmp_path: Path,
) -> None:
    layout, _bundle_path = _bundle(tmp_path)
    layout.native_encoder_path.unlink()
    imported: list[str] = []

    with pytest.raises(BundleSelfCheckError, match="AAC encoder") as raised:
        inspect_bundle(layout, importer=lambda name: imported.append(name))

    assert raised.value.stage == "native-encoder"
    assert imported == []


def test_bundle_self_check_rejects_an_internal_encoder_symlink(tmp_path: Path) -> None:
    layout, _bundle_path = _bundle(tmp_path)
    layout.native_encoder_path.unlink()
    layout.native_encoder_path.symlink_to(layout.native_helper_path)

    with pytest.raises(BundleSelfCheckError, match="AAC encoder") as raised:
        inspect_bundle(layout, importer=lambda _name: None)

    assert raised.value.stage == "native-encoder"


def test_bundle_self_check_identifies_import_without_leaking_exception(tmp_path: Path) -> None:
    layout, _bundle_path = _bundle(tmp_path)

    def importer(module_name: str) -> None:
        if module_name == "keyring.backends.macOS":
            raise RuntimeError("keychain-private-sentinel")

    with pytest.raises(BundleSelfCheckError) as raised:
        inspect_bundle(layout, importer=importer)

    assert raised.value.stage == "import-keyring-backends-macOS"
    assert "keychain-private-sentinel" not in str(raised.value)


def test_bundle_self_check_failure_uses_windowed_safe_stdout(monkeypatch, capsys) -> None:
    def fail() -> None:
        raise BundleSelfCheckError("import-keyring-backends-macOS", "private-sentinel")

    monkeypatch.setattr("meeting_memory.service.bundle_self_check.inspect_bundle", fail)

    assert run_bundle_self_check() == BUNDLE_SELF_CHECK_EXIT_CODES["import-keyring-backends-macOS"]
    captured = capsys.readouterr()
    assert captured.out == (
        "Bundle self-check failed safely at import-keyring-backends-macOS. Reinstall the app.\n"
    )
    assert captured.err == ""
    assert "private-sentinel" not in captured.out

"""Private atomic preference-store tests."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from meeting_memory.service import preference_store_fs
from meeting_memory.service.preference_store import (
    PreferencesConflictError,
    PreferencesDurabilityUncertain,
    PreferencesStoreError,
    PreferenceStore,
)
from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration import (
    AppPreferences,
    CapabilityPreference,
    PreferenceKey,
    PreferenceValue,
    SecretId,
    SecretRef,
)


def test_missing_store_is_empty_without_creating_app_data(tmp_path: Path) -> None:
    path = tmp_path / "app" / "preferences.json"

    assert PreferenceStore(path).load() == AppPreferences()
    assert not path.parent.exists()


def test_round_trip_is_private_atomic_and_contains_no_secret_values(tmp_path: Path) -> None:
    path = tmp_path / "app" / "preferences.json"
    ref = SecretRef(SecretId.BACKUP, "a" * 32)
    preferences = AppPreferences(
        values=(
            PreferenceValue(PreferenceKey.MEETINGS_DIR, "~/Meetings"),
            PreferenceValue(PreferenceKey.B2_BUCKET_NAME, "private-backup"),
        ),
        capabilities=(CapabilityPreference(Capability.BACKUP, True),),
        secret_refs=(ref,),
    )

    store = PreferenceStore(path)
    store.save(preferences)

    assert store.load() == preferences
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    content = path.read_text(encoding="utf-8")
    assert "B2_APPLICATION_KEY" not in content
    assert "application-key-secret-sentinel" not in content


@pytest.mark.parametrize(
    "payload",
    [
        b"not-json",
        json.dumps(
            {
                "schema_version": 99,
                "capabilities": {},
                "values": {},
                "secret_refs": {},
            }
        ).encode(),
        json.dumps(
            {
                "schema_version": 1,
                "capabilities": {},
                "values": {"ASSEMBLYAI_API_KEY": "secret-sentinel"},
                "secret_refs": {},
            }
        ).encode(),
        json.dumps(
            {
                "schema_version": 1,
                "capabilities": {},
                "values": {},
                "secret_refs": {},
                "unknown": "secret-sentinel",
            }
        ).encode(),
        b'{"schema_version":1,"capabilities":{"backup":false,"backup":true},"values":{},"secret_refs":{}}',
        b'{"schema_version":1,"capabilities":{},"values":{"B2_REGION":"a","B2_REGION":"b"},"secret_refs":{}}',
    ],
)
def test_corrupt_unknown_or_secret_bearing_documents_fail_sanitized(
    tmp_path: Path,
    payload: bytes,
) -> None:
    path = tmp_path / "preferences.json"
    path.write_bytes(payload)
    path.chmod(0o600)

    with pytest.raises(PreferencesStoreError) as error:
        PreferenceStore(path).load()

    assert str(path) not in str(error.value)
    assert "secret-sentinel" not in str(error.value)


def test_symlink_fifo_oversize_and_nonowned_files_are_rejected(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(PreferencesStoreError):
        PreferenceStore(link).load()

    fifo = tmp_path / "preferences.fifo"
    os.mkfifo(fifo)
    with pytest.raises(PreferencesStoreError):
        PreferenceStore(fifo).load()

    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b"x" * (preference_store_fs.MAX_PREFERENCES_BYTES + 1))
    oversized.chmod(0o600)
    with pytest.raises(PreferencesStoreError):
        PreferenceStore(oversized).load()

    owned = tmp_path / "owned.json"
    owned.write_text("{}", encoding="utf-8")
    owned.chmod(0o600)
    monkeypatch.setattr(preference_store_fs.os, "getuid", lambda: -1)
    with pytest.raises(PreferencesStoreError):
        PreferenceStore(owned).load()


def test_short_writes_are_completed_without_leaving_temporary_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "app" / "preferences.json"
    original_write = preference_store_fs.os.write

    def short_write(descriptor: int, content: bytes) -> int:
        return original_write(descriptor, content[:3])

    monkeypatch.setattr(preference_store_fs.os, "write", short_write)
    PreferenceStore(path).save(_preferences("short-write"))

    assert PreferenceStore(path).load() == _preferences("short-write")
    assert list(path.parent.glob(".preferences.json.*")) == []


@pytest.mark.parametrize("failure", ["write", "file-fsync", "replace"])
def test_prepublication_failures_preserve_previous_document(
    tmp_path: Path,
    monkeypatch,
    failure: str,
) -> None:
    path = tmp_path / "app" / "preferences.json"
    store = PreferenceStore(path)
    previous_snapshot = store.save(_preferences("previous"))
    previous = path.read_bytes()

    if failure == "write":
        monkeypatch.setattr(preference_store_fs.os, "write", lambda _fd, _content: 0)
    elif failure == "file-fsync":
        monkeypatch.setattr(
            preference_store_fs.os,
            "fsync",
            lambda _fd: (_ for _ in ()).throw(OSError("fsync failed")),
        )
    else:
        monkeypatch.setattr(
            preference_store_fs.os,
            "replace",
            lambda *_args: (_ for _ in ()).throw(OSError("replace failed")),
        )

    with pytest.raises(PreferencesStoreError) as error:
        store.compare_and_swap(previous_snapshot, _preferences("replacement"))

    assert path.read_bytes() == previous
    assert "failed" not in str(error.value)
    assert list(path.parent.glob(".preferences.json.*")) == []


def test_directory_fsync_failure_reports_visible_but_uncertain_replace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "app" / "preferences.json"
    store = PreferenceStore(path)
    previous = store.save(_preferences("previous"))
    monkeypatch.setattr(
        preference_store_fs,
        "_sync_directory",
        lambda _path: (_ for _ in ()).throw(OSError("directory fsync failed")),
    )

    with pytest.raises(PreferencesDurabilityUncertain) as error:
        store.compare_and_swap(previous, _preferences("replacement"))

    visible = PreferenceStore(path).load_snapshot()
    assert visible == error.value.snapshot
    assert visible.preferences == _preferences("replacement")
    assert "directory fsync failed" not in str(error.value)


def test_compare_and_swap_rejects_stale_writer_and_preserves_newer_document(
    tmp_path: Path,
) -> None:
    path = tmp_path / "app" / "preferences.json"
    store = PreferenceStore(path)
    original = store.save(_preferences("original"))
    newer = store.compare_and_swap(original, _preferences("newer"))

    with pytest.raises(PreferencesConflictError):
        store.compare_and_swap(original, _preferences("stale"))

    assert store.load_snapshot() == newer
    fresh = store.load_snapshot()
    saved = store.compare_and_swap(fresh, _preferences("final"))
    assert saved.preferences == _preferences("final")
    assert saved.revision != fresh.revision


def test_save_is_bootstrap_only_and_oversize_output_is_never_published(
    tmp_path: Path,
) -> None:
    path = tmp_path / "app" / "preferences.json"
    store = PreferenceStore(path)
    original = store.save(_preferences("original"))

    with pytest.raises(PreferencesConflictError):
        store.save(_preferences("overwrite"))
    assert store.load_snapshot() == original

    oversized_path = tmp_path / "oversized" / "preferences.json"
    oversized = AppPreferences(
        values=(
            PreferenceValue(
                PreferenceKey.KNOWN_SPEAKERS,
                "x" * preference_store_fs.MAX_PREFERENCES_BYTES,
            ),
        ),
    )
    with pytest.raises(PreferencesStoreError, match="supported size"):
        PreferenceStore(oversized_path).save(oversized)
    assert not oversized_path.exists()


def test_intermediate_symlink_and_unsafe_modes_are_rejected(
    tmp_path: Path,
) -> None:
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(PreferencesStoreError):
        PreferenceStore(linked / "app" / "preferences.json").save(_preferences("x"))

    unsafe_dir = tmp_path / "unsafe"
    unsafe_dir.mkdir(mode=0o755)
    unsafe_dir.chmod(0o755)
    with pytest.raises(PreferencesStoreError):
        PreferenceStore(unsafe_dir / "preferences.json").save(_preferences("x"))

    private_dir = tmp_path / "private"
    private_dir.mkdir(mode=0o700)
    unsafe_file = private_dir / "preferences.json"
    unsafe_file.write_text("{}", encoding="utf-8")
    unsafe_file.chmod(0o644)
    with pytest.raises(PreferencesStoreError):
        PreferenceStore(unsafe_file).load()


def _preferences(folder: str) -> AppPreferences:
    return AppPreferences(
        values=(PreferenceValue(PreferenceKey.MEETINGS_DIR, folder),),
    )

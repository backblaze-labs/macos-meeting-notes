"""Post-replacement preference-store writer safety tests."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest

from meeting_memory.service import preference_store as preference_store_module
from meeting_memory.service import preference_store_fs
from meeting_memory.service.preference_store import (
    PreferencesDurabilityUncertain,
    PreferenceStore,
    snapshot_for_preferences,
)
from meeting_memory.types.configuration import AppPreferences, PreferenceKey, PreferenceValue


def test_post_replace_writer_exit_failure_carries_exact_visible_snapshot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "app" / "preferences.json"
    store = PreferenceStore(path)
    previous = store.save(_preferences("previous"))
    original_locked = preference_store_module.locked_directory

    @contextmanager
    def late_failure(target):
        with original_locked(target) as locked:
            yield locked
        raise OSError("late writer sentinel")

    monkeypatch.setattr(preference_store_module, "locked_directory", late_failure)

    with pytest.raises(PreferencesDurabilityUncertain) as error:
        store.compare_and_swap(previous, _preferences("replacement"))

    assert error.value.snapshot == PreferenceStore(path).load_snapshot()
    assert error.value.snapshot.preferences == _preferences("replacement")
    assert "sentinel" not in str(error.value)


def test_transient_lock_file_open_race_is_retried_safely(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "app" / "preferences.json"
    original_open = preference_store_fs.os.open
    attempts = 0

    def racing_open(target, flags, mode=0o777, *, dir_fd=None):
        nonlocal attempts
        if target == preference_store_fs.LOCK_FILENAME and attempts == 0:
            attempts += 1
            raise FileNotFoundError("simulated lock create race")
        return original_open(target, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(preference_store_fs.os, "open", racing_open)

    saved = PreferenceStore(path).save(_preferences("meetings"))

    assert saved.preferences == _preferences("meetings")
    assert attempts == 1


def test_snapshot_for_preferences_matches_the_exact_saved_document(tmp_path: Path) -> None:
    preferences = _preferences("meetings")
    store = PreferenceStore(tmp_path / "app" / "preferences.json")

    saved = store.save(preferences)

    assert saved == snapshot_for_preferences(preferences)
    assert saved == store.load_snapshot()


def _preferences(folder: str) -> AppPreferences:
    return AppPreferences(
        values=(PreferenceValue(PreferenceKey.MEETINGS_DIR, folder),),
    )

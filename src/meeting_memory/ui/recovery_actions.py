"""Tray-safe filtering for recoveries versus the live capture session."""

from __future__ import annotations

from meeting_memory.service.recovery_index import discover_indexed_recoveries
from meeting_memory.service.runtime_legacy_recovery import LegacyRecoveryRuntime
from meeting_memory.types.recovery import RecoveryIndexEntry, RecoveryOrigin


def is_active_recovery(recorder, recording: RecoveryIndexEntry) -> bool:
    session = getattr(recorder, "active_session", None)
    active = session.recovery if session is not None else None
    if active is None or recording.origin is not RecoveryOrigin.APP_STAGING:
        return False
    return (
        recording.session_device,
        recording.session_inode,
        recording.source_path,
    ) == (active.session_device, active.session_inode, active.source_path)


def list_recoveries(recorder, legacy: LegacyRecoveryRuntime | None):
    temp_dir = getattr(recorder, "temp_dir", None)
    if temp_dir is None:
        return []
    entries = [
        entry
        for entry in discover_indexed_recoveries(temp_dir)
        if not is_active_recovery(recorder, entry)
    ]
    if legacy is not None:
        entries.extend(legacy.entries)
    return entries
